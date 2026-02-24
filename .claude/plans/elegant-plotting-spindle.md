# Projects: Organizational Layer for Training Data

## Context

Currently, the training data dashboard (CuredComponent at `/training-data`) loads ALL texts at once via `NewTextsHandler.list_texts()`. As the number of texts grows, this becomes slow and hard to navigate. Adding a "Projects" layer lets users group texts, see a lightweight project list first, then drill into a specific project to see its texts.

**Scope:** Training data only (CuredComponent). Production texts, model training, and other features stay unchanged. Training pulls curated data globally across all projects.

## Files to Create

### 1. `server-new/src/entities/project.py`

New entity:
```python
class Project(DbModel):
    project_id: int          # Random 7-digit ID
    name: str                # Project name (the only user-facing property)
    created_at: int = -1     # Unix timestamp (same pattern as NewText.use_start_time)
```

### 2. `server-new/src/handlers/projects_handler.py`

Handler following existing `NewTextsHandler` pattern:
- `list_projects()` — returns all projects sorted by `created_at` desc
- `get_project(project_id)` — single project lookup
- `create_project(name) -> int` — creates project, returns project_id
- `rename_project(project_id, name)` — updates name via `$set`
- `delete_project(project_id)` — deletes project document (texts become unassigned)
- `get_project_text_count(project_id) -> int` — counts texts with this project_id

### 3. `server-new/src/api/dto/project.py`

DTOs:
```python
class CreateProjectDto(BaseModel):
    name: str

class RenameProjectDto(BaseModel):
    name: str

class ProjectPreviewDto(BaseModel):
    project_id: int
    name: str
    created_at: int
    text_count: int = 0
    curated_count: int = 0
```

### 4. `server-new/src/api/routers/projects.py`

Router with prefix `/api/v1/projects`:
- `GET /list` — list all projects (returns `ProjectPreviewDto[]` with computed text_count)
- `POST /create` — create project (accepts `CreateProjectDto`, returns project_id)
- `PATCH /{project_id}/rename` — rename project
- `DELETE /{project_id}` — delete project (unsets project_id on its texts)
- `GET /{project_id}/texts` — list texts in project (returns `NewTextPreviewDto[]`)
- `GET /unassigned/texts` — list texts with no project_id

### 5. `app-new/src/app/services/project.service.ts`

Angular service (`providedIn: 'root'`):
- `list()` — GET `/projects/list`
- `create(name)` — POST `/projects/create`
- `rename(projectId, name)` — PATCH `/projects/{id}/rename`
- `delete(projectId)` — DELETE `/projects/{id}`
- `getTexts(projectId)` — GET `/projects/{id}/texts`
- `getUnassignedTexts()` — GET `/projects/unassigned/texts`

## Files to Modify

### 6. `server-new/src/entities/new_text.py` (line 87)

Add `project_id` to `NewText`:
```python
class NewText(DbModel):
    ...
    part: str = ""
    project_id: Optional[int] = None  # NEW
```

### 7. `server-new/src/handlers/new_texts_handler.py`

- Add `list_texts_by_project(project_id)` — `find_many({"project_id": int(project_id)}, ...)`
- Add `list_unassigned_texts()` — find texts where project_id is None
- Modify `create_new_text()` (line 227) — add `project_id: int = None` parameter, pass to NewText constructor
- Add `assign_text_to_project(text_id, project_id)` — `$set` on text
- Add `unassign_texts_from_project(project_id)` — bulk unset for when a project is deleted

### 8. `server-new/src/api/dto/text.py`

- Add `project_id: Optional[int] = None` to `CreateTextDto` (line 14)
- Add `project_id: Optional[int] = None` to `NewTextPreviewDto` (line 62)
- Update `from_new_text()` to include `project_id=getattr(new_text, 'project_id', None)`

### 9. `server-new/src/api/routers/text.py`

- Update `create` endpoint to pass `dto.project_id` to `create_new_text()`

### 10. `server-new/src/common/global_handlers.py`

Add:
```python
from handlers.projects_handler import ProjectsHandler
global_projects_handler = ProjectsHandler()
```

### 11. `server-new/src/main.py` (line 22-23)

Register the projects router:
```python
from api.routers import cured, about, yolo_training, production, ebl, projects
...
app.include_router(projects.router)
```

### 12. `app-new/src/app/models/cured.ts`

Add:
```typescript
export class ProjectPreview {
    constructor(
        public project_id: number,
        public name: string,
        public created_at: number,
        public text_count: number = 0,
        public curated_count: number = 0
    ) {}
}
```

### 13. `app-new/src/app/services/text.service.ts` (line 43)

Update `create()` to accept optional `projectId`:
```typescript
create(textIdentifiers: TextIdentifiers, metadata = [], projectId: number = null) {
    const body: any = { text_identifiers: textIdentifiers, metadata };
    if (projectId) { body.project_id = projectId; }
    return this.http.post<number>(..., body);
}
```

### 14. `app-new/src/app/components/cure-d/cured.component.ts`

**New state:**
```typescript
projects: ProjectPreview[] = [];
selectedProject: ProjectPreview | null = null;
showProjectList: boolean = true;
newProjectName: string = '';
```

**New methods:**
- `loadProjects()` — calls `projectService.list()`
- `selectProject(project)` — sets `selectedProject`, loads texts via `projectService.getTexts()`
- `backToProjects()` — resets to project list view
- `createProject()` — calls `projectService.create()`, reloads list
- `deleteProject(project)` — confirms, calls delete, reloads
- `renameProject(project)` — prompts, calls rename
- `loadUnassignedTexts()` — calls `projectService.getUnassignedTexts()`

**Modify `ngOnInit()`** (line 580): replace `this.loadTransliterationList()` with `this.loadProjects()`

**Modify `handleQueryParams()`** (line 660): on reset to dashboard, call `loadProjects()` instead of `loadTransliterationList()`

**Modify `goBack()`** (stage 2 → stage 0 transition): reload project texts, not all texts

**Modify `createTextAndSaveWithLabelAndPart()`**: pass `this.selectedProject?.project_id` to `textService.create()`

### 15. `app-new/src/app/components/cure-d/cured.component.html`

Restructure stage 0 into two views:

**A) Project list view** (`*ngIf="showProjectList"`):
- "Projects" header with count
- Create-project row: input + button
- Project cards: name, text count, curated count, rename/delete buttons
- "View Unassigned Texts" link at bottom
- Upload zone stays visible alongside projects

**B) Text list view** (`*ngIf="!showProjectList"`):
- Back arrow + project name header
- Existing text list table (filter bar, columns, items) — unchanged
- Upload zone stays visible

### 16. `app-new/src/app/components/cure-d/cured.component.scss`

Add styles for:
- `.create-project-row` — flex row with input + button
- `.project-list` — flex column container
- `.project-card` — clickable card with name, meta, action buttons
- `.unassigned-link` — bottom link section

## Implementation Order

1. Backend entity: `project.py` + add `project_id` to `NewText`
2. Backend handler: `projects_handler.py`
3. Backend handler: add `list_texts_by_project` etc. to `NewTextsHandler`
4. Backend DTOs: `project.py` + update `text.py`
5. Backend router: `projects.py` + register in `main.py` + `global_handlers.py`
6. Frontend model + service: `ProjectPreview` + `project.service.ts`
7. Frontend component: add project state/methods to `cured.component.ts`
8. Frontend template: restructure stage 0 in `.html`
9. Frontend styles: add project card styles in `.scss`
10. Update `text.service.ts` `create()` to pass project_id
11. Build and verify

## Backward Compatibility

- `NewText.project_id` defaults to `None` — existing texts parse fine
- "View Unassigned Texts" lets users access legacy texts without a project
- Training stays global: `get_curated_training_data()` and `get_curated_training_data_for()` remain unchanged
- No migration needed — old data works as-is

## Verification

1. Start server → no errors on startup
2. `GET /api/v1/projects/list` → returns `[]` (empty)
3. `POST /api/v1/projects/create` with `{"name": "Test Project"}` → returns project_id
4. `GET /api/v1/projects/list` → returns 1 project with `text_count: 0`
5. Frontend: navigate to `/training-data` → see project list with "Test Project"
6. Click project → see empty text list
7. Upload image, do OCR, save → text appears in project
8. Back to projects → text_count incremented
9. "View Unassigned Texts" → shows any old texts without project_id
10. Angular build succeeds
