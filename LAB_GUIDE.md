# LAB Guide - Day27 Track 3 HITL PR Review Agent

## 1. Muc tieu bai lab

Ban se xay dung mot agent review Pull Request co Human-in-the-Loop (HITL) bang LangGraph. Ket qua cuoi cung gom:

- Confidence-based routing
- Nhanh human approval bang `interrupt()`
- Nhanh escalation voi cau hoi cu the cho reviewer
- Audit trail bang SQLite
- Giao dien Streamlit de chay end-to-end trong browser

File can hoan thanh:

- `exercises/exercise_1_confidence.py`
- `exercises/exercise_2_hitl.py`
- `exercises/exercise_3_escalation.py`
- `exercises/exercise_4_audit.py`
- `app.py`

## 2. Tong quan luong he thong

Luot chay co dang:

`fetch_pr -> analyze -> route -> auto_approve | human_approval | escalate`

Neu vao nhanh `escalate` thi flow se tiep tuc:

`escalate -> synthesize -> commit`

Nguong confidence can lay theo source of truth trong `common/schemas.py`:

- `confidence >= 0.73` -> `auto_approve`
- `confidence < 0.58` -> `escalate`
- con lai -> `human_approval`

Luu y: mot so comment trong skeleton van nhac den nguong cu. Khi README, comment va code mau mau thuan, uu tien:

1. `common/schemas.py`
2. `pyproject.toml`
3. skeleton hien tai trong repo
4. README

## 3. Cau truc repo

- `common/`: helper da cho san, khong nen sua
- `exercises/`: cac bai can dien `# TODO`
- `audit/`: schema va replay tool
- `app.py`: skeleton cho bai Streamlit
- `README.md`: mo ta bai lab tong quan

## 4. Chuan bi moi truong

### Yeu cau

- Python `3.11+`
- `uv`
- OpenRouter API key
- GitHub Personal Access Token

### Cai dat

```powershell
uv sync
Copy-Item .env.example .env
```

Mo `.env` va dien:

```env
OPENROUTER_API_KEY=...
GITHUB_TOKEN=...
```

### Ghi chu quan trong

- Repo nay da co `streamlit` trong `pyproject.toml`, khong can them dependency nua.
- Lab hien tai dung SQLite (`hitl_audit.db`), khong can cai Postgres.
- GitHub PAT can du scope de doc PR diff va post review comment.

### Kiem tra nhanh

- `uv sync` chay xong khong loi
- `.env` ton tai va co du 2 key
- Co the goi duoc GitHub API bang token cua ban

## 5. Demo PR can dung de test

- PR #1: `https://github.com/VinUni-AI20k/PR-Demo/pull/1`
  - Mong doi: `human_approval`
- PR #2: `https://github.com/VinUni-AI20k/PR-Demo/pull/2`
  - Mong doi: `escalate`

Neu LLM qua tu tin va khong roi vao nhanh mong doi, co the tam thoi dieu chinh threshold trong `common/schemas.py` de debug, nhung nen tra lai gia tri goc sau khi test.

## 6. Cach lam bai duoc khuyen nghi

Lam dung thu tu:

1. Exercise 1
2. Exercise 2
3. Exercise 3
4. Exercise 4
5. Exercise 5

Sau moi exercise:

- Doc het cac `# TODO` trong file
- Hoan thanh toan bo phan con thieu
- Chay lenh test ngay
- Chi sang bai tiep theo khi bai truoc da chay on

## 7. Exercise 1 - Confidence routing

File: `exercises/exercise_1_confidence.py`

### Muc tieu

Dung graph co 3 viec chinh:

- lay PR tu GitHub
- goi LLM de phan tich
- route theo confidence

### Viec can lam

1. Hoan thanh `node_analyze`
   - Tao `llm = get_llm().with_structured_output(PRAnalysis)`
   - Prompt bang `pr_title` va `pr_diff`
   - Tra ve `{"analysis": analysis}`
2. Hoan thanh `node_route`
   - Doc `state["analysis"].confidence`
   - So sanh voi `AUTO_APPROVE_THRESHOLD` va `ESCALATE_THRESHOLD`
   - Tra ve `{"decision": ...}`
3. Hoan thanh `build_graph`
   - `add_node(...)`
   - `add_edge(START, "fetch_pr")`
   - `add_edge("fetch_pr", "analyze")`
   - `add_edge("analyze", "route")`
   - `add_conditional_edges(...)`
   - Noi cac node terminal ve `END`

### Lenh chay

```powershell
uv run python exercises/exercise_1_confidence.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/1
uv run python exercises/exercise_1_confidence.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/2
```

### Tieu chi dat

- 2 PR cho ra 2 nhanh khac nhau
- Co in `confidence`
- Co `final_action`

### Loi de gap

- Dung threshold theo comment cu thay vi `common/schemas.py`
- Chua return dung key `analysis` hoac `decision`
- Wire graph thieu `conditional_edges`

## 8. Exercise 2 - HITL voi interrupt()

File: `exercises/exercise_2_hitl.py`

### Muc tieu

Bien nhanh `human_approval` thanh mot diem pause/resume that su.

### Viec can lam

1. Hoan thanh `node_human_approval`
   - Goi `interrupt(...)`
   - Payload nen co:
     - `kind="approval_request"`
     - `confidence`
     - `confidence_reasoning`
     - `summary`
     - `comments`
     - `diff_preview`
   - Sau khi resume, tra ve:
     - `human_choice`
     - `human_feedback`
2. Hoan thanh `build_graph`
   - Compile voi `checkpointer=MemorySaver()`
3. Hoan thanh `main()`
   - Viet vong lap:
   ```python
   while "__interrupt__" in result:
       payload = result["__interrupt__"][0].value
       answer = prompt_human(payload)
       result = app.invoke(Command(resume=answer), cfg)
   ```

### Lenh chay

```powershell
uv run python exercises/exercise_2_hitl.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/1
```

### Tieu chi dat

- Terminal dung lai tai buoc approve/reject/edit
- Nhap lua chon xong graph chay tiep
- Neu `approve` thi nhanh `commit` co the post comment

### Loi de gap

- Quen `MemorySaver()` nen `interrupt()` khong pause dung cach
- Dung `thread_id` khong nhat quan khi resume
- Dat side effect truoc `interrupt()` dan den duplicate action sau resume

## 9. Exercise 3 - Escalation voi reviewer Q&A

File: `exercises/exercise_3_escalation.py`

### Muc tieu

Neu confidence thap, agent khong hoi approve/reject ngay ma hoi reviewer cac cau cu the, sau do tong hop lai review.

### Viec can lam

1. Cap nhat prompt trong `node_analyze`
   - Yeu cau LLM: neu confidence thap thi dien `escalation_questions`
   - Nen sinh 2-4 cau hoi co context, gan voi file/phan diff cu the
2. Hoan thanh `node_escalate`
   - Goi `interrupt(...)`
   - Payload nen co:
     - `kind="escalation"`
     - `pr_url`
     - `confidence`
     - `confidence_reasoning`
     - `summary`
     - `risk_factors`
     - `questions`
   - Sau resume tra ve `{"escalation_answers": answers}`
3. Hoan thanh `node_synthesize`
   - Doc `state["escalation_answers"]`
   - Goi lai `get_llm().with_structured_output(PRAnalysis)`
   - Prompt gom:
     - diff goc
     - initial analysis
     - reviewer Q&A
   - Tra ve `{"analysis": refined}`
4. Noi graph:
   - `escalate -> synthesize -> commit`

### Lenh chay

```powershell
uv run python exercises/exercise_3_escalation.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/2
```

### Tieu chi dat

- Terminal hien danh sach cau hoi
- Reviewer nhap cau tra loi duoc
- Graph chay tiep sang `synthesize`
- Ket qua cuoi co refined review va `final_action`

### Loi de gap

- LLM khong tao `escalation_questions`
  - Co the dung fallback question nhu skeleton
- Prompt synthesize khong dua du context nen refined review khong tot
- Quen noi edge `escalate -> synthesize -> commit`

## 10. Exercise 4 - Structured SQLite audit trail

File chinh:

- `exercises/exercise_4_audit.py`

File tham chieu:

- `common/schemas.py`
- `common/db.py`
- `audit/replay.py`
- `audit/schema.sql`

### Muc tieu

Them audit trail co cau truc va dung `AsyncSqliteSaver` de flow co the resume ben vung.

### Viec can lam

1. Hoan thanh `audit(state, entry)`
   - Goi `write_audit_event(thread_id=..., pr_url=..., entry=...)`
2. Them `AuditEntry` cho `node_analyze`
3. Them `AuditEntry` cho `node_route`
4. Them 2 `AuditEntry` cho `node_human_approval`
   - truoc interrupt
   - sau resume
5. Them `AuditEntry` cho `node_commit`
6. Them `AuditEntry` cho `node_auto_approve`
7. Them 2 `AuditEntry` cho `node_escalate`
   - truoc interrupt
   - sau resume
8. Them `AuditEntry` cho `node_synthesize`

### Nguyen tac dien AuditEntry

- `confidence`
  - lay tu `analysis.confidence` neu da co
  - voi `fetch_pr` thi dung `0.0` nhu skeleton mau
- `risk_level`
  - tinh bang `risk_level_for(confidence)`
  - neu chua analyze thi co the dung trung tinh `"med"`
- `reviewer_id`
  - `None` cho cac buoc tu dong
  - dung `os.environ.get("GITHUB_USER")` cho HITL step neu skeleton yeu cau
- `decision`
  - `pending` khi chua co quyet dinh
  - `auto`, `approve`, `reject`, `edit`, `escalate` tai dung thoi diem
- `reason`
  - co the la `confidence_reasoning`
  - hoac `human_feedback`
  - hoac tom tat ngan gon dieu vua xay ra
- `execution_time_ms`
  - tinh bang `int((time.monotonic() - t0) * 1000)`

### Lenh chay

```powershell
uv run python exercises/exercise_4_audit.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/1
uv run python -m audit.replay --thread <thread_id>
uv run python -m audit.replay --list
```

### Tieu chi dat

- Tao duoc `hitl_audit.db`
- Replay duoc session theo `thread_id`
- Co du event cho cac node quan trong

### Kiem tra them

Co the xem nhanh bang SQLite:

```powershell
sqlite3 hitl_audit.db "SELECT action, confidence, decision, reviewer_id FROM audit_events ORDER BY id;"
```

## 11. Exercise 5 - Streamlit approval UI

File: `app.py`

### Muc tieu

Chuyen flow terminal sang giao dien web bang Streamlit.

### Viec can lam

1. Import hoac tai su dung graph tu exercise 4
   - Uu tien tai su dung `build_graph(cp)` thay vi copy lai toan bo logic
2. Hoan thanh sidebar recent sessions
   - Query `audit_events`
   - Hien `thread_id`, `pr_url`, `worst_risk`, `last_event`
3. Hoan thanh `render_approval_card(payload)`
   - Hien summary, comment, diff preview
   - 3 nut:
     - Approve -> `{"choice": "approve", "feedback": feedback}`
     - Reject -> `{"choice": "reject", "feedback": feedback}`
     - Edit -> `{"choice": "edit", "feedback": feedback}`
4. Hoan thanh `render_escalation_card(payload)`
   - Tao mot `text_input` cho moi cau hoi
   - Tra ve dict `{question: answer}`
5. Hoan thanh `run_graph(...)`
   - Tao `AsyncSqliteSaver`
   - `await cp.setup()`
   - `app = build_graph(cp)`
   - Neu `resume_value is None` thi invoke voi input ban dau
   - Nguoc lai invoke `Command(resume=resume_value)`
6. Dung `st.session_state`
   - luu `thread_id`
   - luu `pr_url`
   - luu `interrupt_payload`
   - luu `final`

### Hanh vi UI mong doi

- `auto_approve`
  - UI hien success card
  - reviewer khong can thao tac
- `human_approval`
  - UI hien approval card
  - reviewer bam Approve / Reject / Edit
- `escalate`
  - UI hien risk factors
  - reviewer dien cau tra loi
  - graph resume, synthesize, roi moi den final state

### Lenh chay

```powershell
uv run streamlit run app.py
```

### Tieu chi dat

- Nhap duoc PR URL trong browser
- Flow pause dung tai interrupt
- Resume thanh cong
- Hien final state o cuoi flow

## 12. Checklist tu kiem tra cuoi bai

- Exercise 1 route dung theo confidence
- PR #1 vao `human_approval`
- PR #2 vao `escalate`
- Exercise 2 pause/resume dung
- Exercise 3 hoi reviewer va synthesize lai review
- Exercise 4 ghi audit day du vao SQLite
- `audit.replay --thread` xem duoc session
- Streamlit chay end-to-end
- Cung `thread_id` thi resume dung session cu, khong tao session moi
- Nhanh reject khong post comment
- Nhanh approve va auto moi post comment

## 13. Loi thuong gap va cach xu ly

### `interrupt()` nem `GraphInterrupt`

Thuong la do graph compile khong co checkpointer. Kiem tra:

- Exercise 2, 3: `MemorySaver()`
- Exercise 4, 5: `AsyncSqliteSaver`

### Resume bi chay lai tu dau

Nguyen nhan thuong la sai `thread_id`. Phai dung cung `thread_id` giua lan invoke dau va cac lan `Command(resume=...)`.

### Bi post comment trung lap

Ban da dat side effect truoc `interrupt()`. Sau resume, node co the chay lai tu dau. Chuyen side effect xuong node sau, thuong la `commit`.

### `post_review_comment` bi 403 hoac 404

- GitHub token sai scope
- token sai
- repo khong dung quyen truy cap

### Audit schema cu gay loi

Reset bang cach xoa file DB:

```powershell
Remove-Item hitl_audit.db -ErrorAction SilentlyContinue
```

### LLM khong roi vao nhanh mong doi

- Kiem tra lai threshold trong `common/schemas.py`
- Kiem tra prompt co ro rang khong
- Tam thoi dieu chinh threshold de debug

## 14. Chien luoc lam nhanh va an toan

- Exercise 1: lam cho route dung truoc
- Exercise 2: chi tap trung pause/resume
- Exercise 3: chi mo rong nhanh low-confidence
- Exercise 4: log co cau truc, khong sua flow qua nhieu
- Exercise 5: tai su dung toi da logic cua exercise 4

Neu bi tac o exercise sau, quay lai xac nhan exercise truoc van chay on. Lab nay co tinh chat xay tang dan, nen loi nho o bai truoc thuong lan sang bai sau.
