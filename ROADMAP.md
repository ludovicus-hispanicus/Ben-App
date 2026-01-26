# BEn App - Future Features Roadmap

This document outlines planned features for future development after the desktop app is working.

---

## Phase 1: Desktop App Foundation ✅ (Current Focus)

- [ ] Verify babylon-pub Electron wrapper works with current BEn-app
- [ ] Ensure Docker images are up to date
- [ ] Test full workflow on Windows

---

## Phase 2: Remove Authentication

**Goal**: Allow open access without login requirement.

### Backend Changes
- `server/src/auth/auth_bearer.py` - Disable JWT validation or make optional
- `server/src/api/routers/*.py` - Remove `Depends(JWTBearer())` from endpoints
- `server/src/handlers/users_handler.py` - Keep for optional user tracking

### Frontend Changes
- `app/src/app/auth/` - Remove login requirement
- `app/src/app/interceptors/auth.interceptor.ts` - Make token optional
- `app/src/app/home/` - Skip login screen, go directly to main app

### Notes
- Consider keeping optional user identification for tracking contributions
- Could use anonymous session IDs instead

---

## Phase 3: Simplify Output Format

**Goal**: Replace restrictive line-by-line approach with flexible TXT export for training.

### Current Problem
- Output is structured in rigid line-by-line format
- Hard to modify for retraining purposes
- Too restrictive for data collection

### Proposed Solution
- Add "Export as TXT" button
- Simple format: image path + full transliteration text
- Allow free-form editing before export

### Files to Modify
- `server/src/handlers/texts_handler.py` - Add simple export method
- `server/src/api/routers/text.py` - Add TXT export endpoint
- `app/src/app/amendment/` - Add export button to UI

### Export Format Example
```
# text_id: 123
# image: user_upload/123.png
# exported: 2026-01-26

a-na {d}UTU EN GAL-i
EN-ia ŠEŠ-ia
um-ma {m}PN ARAD-ka-a-ma

---
[corrections]
line 1, pos 3: GAL → LUGAL (certainty: ?)
```

---

## Phase 4: Email Export for Training Data

**Goal**: Automatically send user corrections to your email for model retraining.

### Backend Changes

**New files:**
- `server/src/handlers/export_handler.py` - SMTP logic, queue management
- `server/src/api/routers/export.py` - Export API endpoints
- `server/src/api/dto/export_dto.py` - Request/response models

**Modify:**
- `server/src/handlers/texts_handler.py` - Queue corrections on save
- `server/src/handlers/new_texts_handler.py` - Queue transliterations on save
- `server/src/main.py` - Register export router

### Frontend Changes

**New files:**
- `app/src/app/settings/settings.component.ts` - Settings page
- `app/src/app/services/export.service.ts` - Export API client

**Modify:**
- `app/src/app/app-routing.module.ts` - Add settings route
- Navigation - Add settings link

### Database
```javascript
// MongoDB: export_queue collection
{
  data_type: "correction" | "transliteration",
  data: { /* correction data */ },
  created_at: ISODate,
  status: "pending" | "exported"
}

// MongoDB: settings collection
{
  _id: "smtp_config",
  host: "smtp.gmail.com",
  port: 587,
  username: "encrypted",
  password: "encrypted",
  recipient: "training@your-domain.com"
}
```

### Export JSON Format
```json
{
  "version": "1.0",
  "exportDate": "2026-01-26T10:00:00Z",
  "corrections": [...],
  "transliterations": [...],
  "images": [{"name": "...", "base64": "..."}]
}
```

---

## Phase 5: Add Local VLM for Dictionary

**Goal**: Integrate a local Vision Language Model (like LLaVA) for cuneiform sign dictionary/lookup.

### Model Options

| Model | Size | Quality | Notes |
|-------|------|---------|-------|
| LLaVA 1.5 7B | ~7GB | Good | Balanced size/quality |
| LLaVA 1.5 13B | ~13GB | Better | Higher quality, slower |
| Qwen-VL | ~10GB | Good | Alternative option |

### Architecture

```
User selects sign region → Crop image
           ↓
    Send to VLM endpoint
           ↓
    VLM analyzes sign
           ↓
    Return: sign name, reading, meaning, parallels
```

### Backend Changes

**New files:**
- `server/src/handlers/vlm_handler.py` - VLM inference logic
- `server/src/api/routers/dictionary.py` - Dictionary endpoints

**Dependencies:**
- `transformers` - For loading models
- `torch` - Already installed
- `accelerate` - For efficient inference

### Frontend Changes

**New component:**
- `app/src/app/dictionary/` - Dictionary lookup UI
- Selection tool to crop sign from image
- Results display with sign information

### Endpoints
```
POST /api/v1/dictionary/lookup
  - Input: cropped image (base64)
  - Output: { sign_name, readings, meaning, examples }

GET /api/v1/dictionary/search?query=LUGAL
  - Text-based search in sign database
```

### Docker Considerations
- VLM models are large (~7-13GB)
- May need separate container or volume for models
- Consider lazy loading (download on first use)

---

## Priority Order

1. **Desktop App** (now) - Get it working
2. **Remove Auth** - Quick win, opens up access
3. **Simplify Output** - Better training data collection
4. **Email Export** - Automated data collection
5. **VLM Dictionary** - Advanced feature, most complex

---

## Notes

- All features should be backward compatible
- Test each phase before moving to next
- Keep Docker images updated after each change
- Consider feature flags for gradual rollout
