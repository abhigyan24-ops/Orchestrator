-- =============================================================
-- Seed Data — tool_skills + sample project_context
-- =============================================================
-- Priority: 1 = first choice, 2 = fallback, 3 = last resort.
-- Multiple rows per tool allow intra-tool fallback (e.g.
-- Antigravity Pro → Flash) before jumping to another tool.
-- =============================================================

-- ---------------------------------------------------------
-- Frontend skills
-- ---------------------------------------------------------
INSERT INTO tool_skills (tool_name, model_name, task_category, priority, notes) VALUES
    ('antigravity', 'gemini-2.5-pro',   'frontend', 1, 'Best multimodal + UI generation'),
    ('antigravity', 'gemini-2.5-flash', 'frontend', 2, 'Flash fallback within Antigravity'),
    ('cursor',      '',                 'frontend', 3, 'Cursor Hobby tier, general frontend editing'),
    ('v0',          '',                 'frontend', 4, 'Vercel v0 — React component generation')
ON CONFLICT (tool_name, model_name, task_category) DO NOTHING;

-- ---------------------------------------------------------
-- Backend skills
-- ---------------------------------------------------------
INSERT INTO tool_skills (tool_name, model_name, task_category, priority, notes) VALUES
    ('codex',       '',                 'backend',  1, 'ChatGPT/Codex — well-scoped backend tasks'),
    ('antigravity', 'gemini-2.5-pro',   'backend',  2, 'Antigravity Pro for complex backend'),
    ('antigravity', 'gemini-2.5-flash', 'backend',  3, 'Flash fallback'),
    ('cursor',      '',                 'backend',  4, 'Cursor general editing')
ON CONFLICT (tool_name, model_name, task_category) DO NOTHING;

-- ---------------------------------------------------------
-- Database / migration skills
-- ---------------------------------------------------------
INSERT INTO tool_skills (tool_name, model_name, task_category, priority, notes) VALUES
    ('antigravity', 'gemini-2.5-pro',   'db',       1, 'Pro handles complex schema design'),
    ('codex',       '',                 'db',       2, 'Codex for simpler DB tasks'),
    ('cursor',      '',                 'db',       3, 'Cursor fallback')
ON CONFLICT (tool_name, model_name, task_category) DO NOTHING;

-- ---------------------------------------------------------
-- Planning / spec-writing skills
-- ---------------------------------------------------------
INSERT INTO tool_skills (tool_name, model_name, task_category, priority, notes) VALUES
    ('kiro',        '',                 'planning', 1, 'Kiro is purpose-built for planning/specs'),
    ('antigravity', 'gemini-2.5-pro',   'planning', 2, 'Antigravity Pro as planning fallback'),
    ('claude',      'claude-sonnet',    'planning', 3, 'Claude Sonnet for planning')
ON CONFLICT (tool_name, model_name, task_category) DO NOTHING;

-- ---------------------------------------------------------
-- Boilerplate / scaffolding skills
-- ---------------------------------------------------------
INSERT INTO tool_skills (tool_name, model_name, task_category, priority, notes) VALUES
    ('cursor',      '',                 'boilerplate', 1, 'Cursor fast for scaffolding'),
    ('zed',         '',                 'boilerplate', 2, 'Zed for large-codebase boilerplate'),
    ('antigravity', 'gemini-2.5-flash', 'boilerplate', 3, 'Flash for quick boilerplate')
ON CONFLICT (tool_name, model_name, task_category) DO NOTHING;

-- ---------------------------------------------------------
-- Default quota_status rows (all start available)
-- ---------------------------------------------------------
INSERT INTO quota_status (tool_name, model_name, status) VALUES
    ('antigravity', 'gemini-2.5-pro',   'available'),
    ('antigravity', 'gemini-2.5-flash', 'available'),
    ('cursor',      '',                 'available'),
    ('kiro',        '',                 'available'),
    ('codex',       '',                 'available'),
    ('claude',      'claude-sonnet',    'available'),
    ('v0',          '',                 'available'),
    ('zed',         '',                 'available')
ON CONFLICT (tool_name, model_name) DO NOTHING;

-- ---------------------------------------------------------
-- Sample project_context
-- ---------------------------------------------------------
INSERT INTO project_context (project_id, architecture, progress_log, handoff_notes) VALUES
    ('orchestrator',
     'Python 3.11+ / FastAPI / asyncpg / PostgreSQL / FastMCP. '
     'Hosted on Render. MCP server coordinating multiple AI coding tools.',
     'Phase 1: Schema + connection layer built.',
     'Starting from a clean build. All tables created, seed data loaded.')
ON CONFLICT (project_id) DO NOTHING;
