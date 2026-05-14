# DEV Instant Push Rollback Guide

## What Was Changed
- **File**: `routes.py`
- **Lines**: 10872-11074 (function `api_group_push`)
- **Change**: Added `IS_DEVELOPMENT` check for inline vs async push execution

### Summary of Change
In DEV mode (`APP_ENV=dev`), inventory pushes now execute INLINE (immediate) instead of being queued to async workers. This restores the "instant push" behavior that was previously available.

## Rollback Steps

### Option 1: Environment Variable Override (Fastest)
Set `APP_ENV=prod` to force async queue behavior even in development:
```bash
export APP_ENV=prod
# Restart the application
```

### Option 2: Code Revert (Full Rollback)
Revert the `api_group_push` function to always use `enqueue_sync_job`:

1. Open `routes.py`
2. Find function `api_group_push` (around line 10872)
3. Remove the `if IS_DEVELOPMENT:` branch (lines 10924-10998)
4. Keep only the `enqueue_sync_job` path (currently in the `else:` block)
5. Remove the `from app import IS_DEVELOPMENT` import

### Option 3: Git Revert (If Committed)
```bash
# Find the commit that introduced DEV inline push
git log --oneline --all -- routes.py | head -5

# Revert specific commit
git revert <commit_hash>
```

## Verification After Rollback

1. **Restart the application**
   ```bash
   # Workflow will auto-restart, or manually restart
   ```

2. **Trigger a test push from Product Linking page**

3. **Check logs for async behavior**:
   - Should see: `[GROUP_PUSH] Queued job <id> for <platform>`
   - Should NOT see: `[GROUP_PUSH][DEV-INLINE]`

4. **Confirm push mode in logs**:
   - Should see: `[PUSH_MODE] prod-async`
   - Should NOT see: `[PUSH_MODE] dev-inline`

## Files Modified in This Change

| File | Lines | Description |
|------|-------|-------------|
| routes.py | 10872-11074 | api_group_push function with IS_DEVELOPMENT branching |

## Related Files (Unchanged)

| File | Purpose |
|------|---------|
| app.py | Contains IS_DEVELOPMENT flag (line 38) |
| sync_service.py | Contains sync_warehouse_stock_to_store function |
| queue_manager.py | Contains enqueue_sync_job function |

## Emergency Contacts
- System Architecture: See `replit.md` for system overview
- Push Architecture: `/api/group-push` is the ONLY active push endpoint

## Change Log
| Date | Author | Description |
|------|--------|-------------|
| 2025-12-14 | Agent | Initial DEV instant push implementation |
