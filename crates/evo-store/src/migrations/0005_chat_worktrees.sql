-- 0005: a chat can work in a managed Git worktree of its workspace's
-- repository (a nested session started with `worktree: true`). Its engine
-- runs there instead of in the workspace folder; NULL is the workspace itself.

ALTER TABLE chats ADD COLUMN worktree_path TEXT;
