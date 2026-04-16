# Git SOP for Xero

## Commit Message Format

Use Conventional Commits: `<type>(<scope>): <description>`

### Types
- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Code style/formatting (no logic changes)
- **refactor**: Code restructuring (no behavior changes)
- **test**: Adding/modifying tests
- **chore**: Maintenance tasks (build, deps, etc.)

### Scope (Optional)
Brief identifier for the affected area, e.g., `sync`, `api`, `ui`, `docs`

### Description
- Imperative mood (e.g., "add", "fix", not "added", "fixed")
- Start lowercase
- No period at end
- Keep under 72 characters

### Examples
- `feat(sync): add bidirectional invoice sync`
- `fix(api): handle Xero contact dependency fields`
- `docs: update codebase reference sheet`
- `chore: upgrade account mappings feature`

### Additional Guidelines
- Use present tense
- Reference issues/PRs if applicable (e.g., `feat(sync): add bidirectional invoice sync (#123)`)
- For breaking changes, add `BREAKING CHANGE:` footer

## Repository Remotes

- Upstream remote: `https://github.com/EPIUSECX/cohenix_bma_xero.git`
- Main branch tracks: upstream/main