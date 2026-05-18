# Reverse Engineering

**Purpose**: Analyze existing codebase and generate comprehensive design artifacts

**Execute when**: Brownfield project detected (existing code found in workspace)

**Skip when**: Greenfield project (no existing code)

**Rerun behavior**: Rerun is controlled by workspace-detection.md. If existing reverse engineering artifacts are found and are still current, they are loaded and reverse engineering is skipped. If artifacts are stale (older than the codebase's last significant modification) or the user explicitly requests a rerun, reverse engineering executes again to ensure artifacts reflect current code state

---

# ⚠️ CRITICAL: MANDATORY ARTIFACT GENERATION

**YOU MUST generate ALL 9 artifacts listed below. This is NOT optional.**

**Why this matters**:
- `code-structure.md` and `api-documentation.md` are REQUIRED for brownfield cost optimization in code-generation stage
- Without these files, the existence check cannot run → agent generates full code → wastes $4-10

**Enforcement**: Each artifact MUST be written with `write_aidlc_artifact`. Do NOT collapse multiple artifacts into a single "summary.md" file.

---

## Step 1: Multi-Package Discovery

### 1.1 Scan Workspace
- All packages (not just mentioned ones)
- Package relationships via config files
- Package types: Application, CDK/Infrastructure, Models, Clients, Tests

### 1.2 Understand the Business Context
- The core business that the system is implementing overall
- The business overview of every package
- List of Business Transactions that are implemented in the system

### 1.3 Infrastructure Discovery
- CDK packages (package.json with CDK dependencies)
- Terraform (.tf files)
- CloudFormation (.yaml/.json templates)
- Deployment scripts

### 1.4 Build System Discovery
- Build systems: Brazil, Maven, Gradle, npm
- Config files for build-system declarations
- Build dependencies between packages

### 1.5 Service Architecture Discovery
- Lambda functions (handlers, triggers)
- Container services (Docker/ECS configs)
- API definitions (Smithy models, OpenAPI specs)
- Data stores (DynamoDB, S3, etc.)

### 1.6 Code Quality Analysis
- Programming languages and frameworks
- Test coverage indicators
- Linting configurations
- CI/CD pipelines

## Step 2: Generate Business Overview Documentation (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/business-overview.md` with the following content:

```markdown
# Business Overview

## Business Context Diagram
[Mermaid diagram showing the Business Context]

## Business Description
- **Business Description**: [Overall Business description of what the system does]
- **Business Transactions**: [List of Business Transactions that the system implements and their descriptions]
- **Business Dictionary**: [Business dictionary terms that the system follows and their meaning]

## Component Level Business Descriptions
### [Package/Component Name]
- **Purpose**: [What it does from the business perspective]
- **Responsibilities**: [Key responsibilities]
```

## Step 3: Generate Architecture Documentation (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/architecture.md` with the following content:

```markdown
# System Architecture

## System Overview
[High-level description of the system]

## Architecture Diagram
[Mermaid diagram showing all packages, services, data stores, relationships]

## Component Descriptions
### [Package/Component Name]
- **Purpose**: [What it does]
- **Responsibilities**: [Key responsibilities]
- **Dependencies**: [What it depends on]
- **Type**: [Application/Infrastructure/Model/Client/Test]

## Data Flow
[Mermaid sequence diagram of key workflows]

## Integration Points
- **External APIs**: [List with purposes]
- **Databases**: [List with purposes]
- **Third-party Services**: [List with purposes]

## Infrastructure Components
- **CDK Stacks**: [List with purposes]
- **Deployment Model**: [Description]
- **Networking**: [VPC, subnets, security groups]
```

## Step 4: Generate Code Structure Documentation (MANDATORY - CRITICAL FOR BROWNFIELD)

**🚨 CRITICAL**: This file is REQUIRED for brownfield cost optimization. Without it, code-generation will waste $4-10.

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/code-structure.md` with the following content:

```markdown
# Code Structure

## Build System
- **Type**: [Maven/Gradle/npm/Brazil]
- **Configuration**: [Key build files and settings]

## Key Classes/Modules
[Mermaid class diagram or module hierarchy]

### Existing Files Inventory
[List all source files with their purposes - these are candidates for modification in brownfield projects]

**Example format**:
- `[path/to/file]` - [Purpose/responsibility]

## Design Patterns
### [Pattern Name]
- **Location**: [Where used]
- **Purpose**: [Why used]
- **Implementation**: [How implemented]

## Critical Dependencies
### [Dependency Name]
- **Version**: [Version number]
- **Usage**: [How and where used]
- **Purpose**: [Why needed]
```

## Step 5: Generate API Documentation (MANDATORY - CRITICAL FOR BROWNFIELD)

**🚨 CRITICAL**: This file is REQUIRED for brownfield cost optimization. Without it, code-generation will waste $4-10.

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/api-documentation.md` with the following content:

```markdown
# API Documentation

## REST APIs
### [Endpoint Name]
- **Method**: [GET/POST/PUT/DELETE]
- **Path**: [/api/path]
- **Purpose**: [What it does]
- **Request**: [Request format]
- **Response**: [Response format]

## Internal APIs
### [Interface/Class Name]
- **Methods**: [List with signatures]
- **Parameters**: [Parameter descriptions]
- **Return Types**: [Return type descriptions]

## Data Models
### [Model Name]
- **Fields**: [Field descriptions]
- **Relationships**: [Related models]
- **Validation**: [Validation rules]
```

## Step 6: Generate Component Inventory (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/component-inventory.md` with the following content:

```markdown
# Component Inventory

## Application Packages
- [Package name] - [Purpose]

## Infrastructure Packages
- [Package name] - [CDK/Terraform] - [Purpose]

## Shared Packages
- [Package name] - [Models/Utilities/Clients] - [Purpose]

## Test Packages
- [Package name] - [Integration/Load/Unit] - [Purpose]

## Total Count
- **Total Packages**: [Number]
- **Application**: [Number]
- **Infrastructure**: [Number]
- **Shared**: [Number]
- **Test**: [Number]
```

## Step 7: Generate Technology Stack Documentation (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/technology-stack.md` with the following content:

```markdown
# Technology Stack

## Programming Languages
- [Language] - [Version] - [Usage]

## Frameworks
- [Framework] - [Version] - [Purpose]

## Infrastructure
- [Service] - [Purpose]

## Build Tools
- [Tool] - [Version] - [Purpose]

## Testing Tools
- [Tool] - [Version] - [Purpose]
```

## Step 8: Generate Dependencies Documentation (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/dependencies.md` with the following content:

```markdown
# Dependencies

## Internal Dependencies
[Mermaid diagram showing package dependencies]

### [Package A] depends on [Package B]
- **Type**: [Compile/Runtime/Test]
- **Reason**: [Why dependency exists]

## External Dependencies
### [Dependency Name]
- **Version**: [Version]
- **Purpose**: [Why used]
- **License**: [License type]
```

## Step 9: Generate Code Quality Assessment (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/code-quality-assessment.md` with the following content:

```markdown
# Code Quality Assessment

## Test Coverage
- **Overall**: [Percentage or Good/Fair/Poor/None]
- **Unit Tests**: [Status]
- **Integration Tests**: [Status]

## Code Quality Indicators
- **Linting**: [Configured/Not configured]
- **Code Style**: [Consistent/Inconsistent]
- **Documentation**: [Good/Fair/Poor]

## Technical Debt
- [Issue description and location]

## Patterns and Anti-patterns
- **Good Patterns**: [List]
- **Anti-patterns**: [List with locations]
```

## Step 10: Create Timestamp File (MANDATORY)

**REQUIRED**: You MUST call `write_aidlc_artifact` to create `inception/reverse-engineering/reverse-engineering-timestamp.md` with the following content:

```markdown
# Reverse Engineering Metadata

**Analysis Date**: [ISO timestamp]
**Analyzer**: AI-DLC
**Workspace**: [Workspace path]
**Total Files Analyzed**: [Number]

## Artifacts Generated
- [x] business-overview.md
- [x] architecture.md
- [x] code-structure.md
- [x] api-documentation.md
- [x] component-inventory.md
- [x] technology-stack.md
- [x] dependencies.md
- [x] code-quality-assessment.md
```

## Step 11: MANDATORY VALIDATION - Verify All 9 Artifacts Written

**🚨 CRITICAL VALIDATION CHECKPOINT**

Before proceeding, you MUST verify that ALL 9 artifacts were written. If ANY are missing, this stage has FAILED and you must regenerate the missing artifacts.

**Required artifacts checklist:**
1. ✓ `business-overview.md`
2. ✓ `architecture.md`
3. ✓ `code-structure.md` ← CRITICAL for brownfield
4. ✓ `api-documentation.md` ← CRITICAL for brownfield
5. ✓ `component-inventory.md`
6. ✓ `technology-stack.md`
7. ✓ `dependencies.md`
8. ✓ `code-quality-assessment.md`
9. ✓ `reverse-engineering-timestamp.md`

**How to verify:**
- Review your `write_aidlc_artifact` tool calls in this conversation
- Count: Did you call it exactly 9 times for the files above?
- If NO: Generate the missing artifacts NOW before proceeding

**INVALID shortcuts that will break brownfield optimization:**
- ❌ Writing a single `summary.md` instead of 9 files
- ❌ Combining multiple artifacts into one file
- ❌ Skipping artifacts because "the project is simple"
- ❌ Assuming files are optional

**If you wrote `summary.md` instead of the 9 required files, you have FAILED this stage.**

## Step 12: Update State Tracking

Update `aidlc-docs/aidlc-state.md`:

```markdown
## Reverse Engineering Status
- [x] Reverse Engineering - Completed on [timestamp]
- **Artifacts Location**: aidlc-docs/inception/reverse-engineering/
- **Artifacts Generated**: 9 (business-overview, architecture, code-structure, api-documentation, component-inventory, technology-stack, dependencies, code-quality-assessment, timestamp)
```

## Step 13: Present Completion Message to User

```markdown
# 🔍 Reverse Engineering Complete

[AI-generated summary of key findings from analysis in the form of bullet points]

> **📋 <u>**REVIEW REQUIRED:**</u>**  
> Please examine the reverse engineering artifacts at: `aidlc-docs/inception/reverse-engineering/`

> **🚀 <u>**WHAT'S NEXT?**</u>**
>
> **You may:**
>
> 🔧 **Request Changes** - Ask for modifications to the reverse engineering analysis if required
> ✅ **Approve & Continue** - Approve analysis and proceed to **Requirements Analysis**
```

## Step 14: Wait for User Approval

- **MANDATORY**: Do not proceed until user explicitly approves
- **MANDATORY**: Log user's response in audit.md with complete raw input
