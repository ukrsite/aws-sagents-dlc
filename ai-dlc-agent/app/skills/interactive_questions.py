"""Parse and interactively answer requirement-verification-questions.md in the terminal."""

from __future__ import annotations

import re
import signal
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QuestionOption:
    letter: str   # "A", "B", "C", "X"
    text: str     # option description


@dataclass
class Question:
    number: str                                    # "1.1", "2.3", etc.
    title: str                                     # section heading
    text: str                                      # question body
    options: list[QuestionOption] = field(default_factory=list)
    considerations: list[str] = field(default_factory=list)
    answer: str | None = None                      # filled in by user; None means unanswered


def parse_questions(content: str) -> list[Question]:
    """Parse the questions markdown into structured Question objects."""
    questions: list[Question] = []

    # Split on "---" separators OR on "### Question N" / "### N.N" headings.
    # This handles both formats the agent may generate.
    raw_blocks = re.split(r"\n---\n", content)

    # If no --- separators found, try splitting on ### headings
    if len(raw_blocks) <= 1:
        raw_blocks = re.split(r"(?=\n###\s)", content)

    blocks = raw_blocks

    for block in blocks:
        block = block.strip()
        if not block or "[Answer]:" not in block:
            continue

        heading_match = re.search(r"###\s+([\d.]+)\s+(.+)", block)
        if not heading_match:
            # Try "### Question N" or "### N. Title" format
            heading_match = re.search(r"###\s+(?:Question\s+)?(\d+)\.?\s*(.*)", block, re.IGNORECASE)
            if heading_match:
                number = heading_match.group(1).strip()
                title = heading_match.group(2).strip() or f"Question {number}"
            else:
                # Try "## Q1. Title" or "## 1. Title" format
                heading_match = re.search(r"##\s+Q?(\d+)\.\s+(.+)", block, re.IGNORECASE)
                if heading_match:
                    number = heading_match.group(1).strip()
                    title = heading_match.group(2).strip()
                else:
                    continue
        else:
            number = heading_match.group(1).strip()
            title = heading_match.group(2).strip()

        q_match = re.search(
            r"\*\*Question\*\*:\s*(.+?)(?=\n\*\*|\n-\s+[A-X]\)|\[Answer\])",
            block, re.DOTALL
        )
        question_text = q_match.group(1).strip() if q_match else title

        options = []
        # Match both "- A) text" and "A) text" formats
        for opt_match in re.finditer(
            r"(?:^|\n)-?\s*([A-X])\)\s+(.+?)(?=\n-?\s*[A-X]\)|\[Answer\]|\Z)",
            block, re.DOTALL
        ):
            letter = opt_match.group(1)
            text = opt_match.group(2).strip().replace("\n", " ")
            if len(text) > 100:
                text = text[:97] + "..."
            options.append(QuestionOption(letter=letter, text=text))

        considerations = []
        for bullet_match in re.finditer(r"^-\s+(?![A-X]\))(.+)$", block, re.MULTILINE):
            text = bullet_match.group(1).strip()
            if text and len(text) > 5:
                considerations.append(text)

        answer_match = re.search(r"\[Answer\]:\s*(.*)$", block, re.MULTILINE)
        existing_answer = answer_match.group(1).strip() if answer_match else ""

        questions.append(Question(
            number=number,
            title=title,
            text=question_text,
            options=options,
            considerations=considerations,
            answer=existing_answer,
        ))

    return questions


def write_answers_back(questions_path: Path, questions: list[Question]) -> None:
    """Write user answers back into the [Answer]: tags in the file."""
    content = questions_path.read_text(encoding="utf-8")
    for q in questions:
        if not q.answer:
            continue
        pattern = rf"(###\s+{re.escape(q.number)}\s+.+?)\[Answer\]:\s*[^\n]*"
        replacement = rf"\g<1>[Answer]: {q.answer}"
        new_content = re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)
        if new_content != content:
            content = new_content
    questions_path.write_text(content, encoding="utf-8")


def _read_line_timeout(timeout: int) -> str:
    """Read a line from stdin with a timeout. Returns empty string on timeout or interrupt."""
    def _handler(signum: int, frame: object) -> None:
        raise TimeoutError()

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        return input().strip()
    except TimeoutError:
        return ""
    except EOFError:
        return ""
    except KeyboardInterrupt:
        print()
        return "skip"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _parse_compact_answers(
    raw: str,
    questions: list[Question],
    labels: str,
) -> None:
    """
    Parse compact answer string like "A1 B3 C free text D2".

    A1 = question A, option 1
    B free text = question B, free-text answer
    """
    tokens = raw.strip().split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # "A1" style — letter + digit
        m = re.match(r"^([A-Za-z])(\d+)$", token)
        if m:
            q_letter = m.group(1).upper()
            opt_num = int(m.group(2))
            q_idx = labels.upper().find(q_letter)
            if 0 <= q_idx < len(questions):
                q = questions[q_idx]
                if q.options and 1 <= opt_num <= len(q.options):
                    q.answer = f"{q.options[opt_num - 1].letter}) {q.options[opt_num - 1].text[:60]}"
                else:
                    q.answer = token
            i += 1
            continue

        # "A" alone — free-text follows until next "X\d" token
        m2 = re.match(r"^([A-Za-z])$", token)
        if m2:
            q_letter = m2.group(1).upper()
            q_idx = labels.upper().find(q_letter)
            text_parts = []
            j = i + 1
            while j < len(tokens):
                if re.match(r"^[A-Za-z]\d*$", tokens[j]):
                    break
                text_parts.append(tokens[j])
                j += 1
            if 0 <= q_idx < len(questions) and text_parts:
                questions[q_idx].answer = " ".join(text_parts)
            i = j
            continue

        i += 1


def run_interactive_questions(questions_path: Path) -> bool:
    """
    Display all unanswered questions at once in a compact format.
    User answers with a single line like: A1 B2 C free text D3

    Returns True if completed, False if aborted.
    """
    content = questions_path.read_text(encoding="utf-8")
    questions = parse_questions(content)
    unanswered = [q for q in questions if not q.answer]

    if not unanswered:
        try:
            from rich.console import Console
            Console().print(
                "\n[dim]ℹ️  All clarifying questions already have answers (resuming previous session).[/dim]\n"
                f"[dim]   Review answers in: {questions_path}[/dim]\n"
            )
        except ImportError:
            print(f"\nℹ️  All questions already answered. Review: {questions_path}\n", flush=True)
        return True

    # Cap at 6 questions to keep it concise.
    unanswered = unanswered[:6]
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    try:
        from rich.console import Console
        from rich.panel import Panel
        console = Console()
        console.print()

        lines = []
        for idx, q in enumerate(unanswered):
            lbl = labels[idx]
            # Short title only — no verbose question text
            lines.append(f"[bold cyan]{lbl}.[/bold cyan] [white]{q.title}[/white]")
            if q.options:
                for i, opt in enumerate(q.options, 1):
                    lines.append(f"   [green]{i})[/green] {opt.text[:90]}")
            elif q.considerations:
                for c in q.considerations[:3]:
                    lines.append(f"   [dim]• {c[:90]}[/dim]")
            lines.append("")

        answer_hint = " ".join(f"[cyan]{labels[i]}[/cyan]?" for i in range(len(unanswered)))
        lines.append(
            f"[bold]Answer:[/bold] {answer_hint}  "
            "[dim](e.g. A1 B2 C free text — or 'skip' / 'abort')[/dim]"
        )

        console.print(
            Panel(
                "\n".join(lines),
                title="[bold yellow]📋  Requirements Clarification[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        raw = _read_line_timeout(300)

        if raw.lower() == "abort":
            console.print("[red]Aborted.[/red]")
            return False

        if raw.lower() in ("skip", ""):
            console.print("[dim]Skipped.[/dim]")
            return True

        _parse_compact_answers(raw, unanswered, labels)

        # Show what was recorded
        for idx, q in enumerate(unanswered):
            if q.answer:
                console.print(f"  [dim]→ {labels[idx]}: {q.answer[:70]}[/dim]")

        write_answers_back(questions_path, questions)
        console.print("[green]✅  Answers saved.[/green]")

    except ImportError:
        print(f"\n📋  {len(unanswered)} question(s):\n", flush=True)
        for idx, q in enumerate(unanswered):
            lbl = labels[idx]
            print(f"{lbl}. {q.title}", flush=True)
            for i, opt in enumerate(q.options, 1):
                print(f"   {i}) {opt.text[:90]}", flush=True)
            if not q.options:
                for c in q.considerations[:2]:
                    print(f"   • {c[:90]}", flush=True)
        hint = " ".join(f"{labels[i]}?" for i in range(len(unanswered)))
        print(f"\nAnswer ({hint}): ", end="", flush=True)
        raw = _read_line_timeout(300)
        if raw.lower() not in ("abort", "skip", ""):
            _parse_compact_answers(raw, unanswered, labels)
        write_answers_back(questions_path, questions)

    return True
