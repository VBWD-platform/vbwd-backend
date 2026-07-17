# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Token-movement hook seam** (S138.0) — `vbwd/services/token_balance_hooks.py`: `ITokenMovementHook` / `TokenMovement` + registry, run by `TokenService` inside each movement's transaction (before commit). Lets an external bookkeeper mirror the token balance atomically; a raising hook rolls the movement back. Plus a best-effort `token.moved` EventBus event after commit. See `docs/developer/token-movement-hooks.md`.
- AST oracle (`tests/unit/test_token_balance_write_oracle.py`) enforcing that `TokenService` is the only site that mutates `UserTokenBalance.balance` or constructs a `TokenTransaction`.

### Changed
- `TokenService` is now one unit of work per movement: the balance change and its `TokenTransaction` commit **together** (fixes a latent double-commit where a failure between the two could leave a balance change with no ledger row). `credit_tokens` / `debit_tokens` gain `commit=False` to compose in a caller's transaction.
- Admin `PUT /api/v1/admin/users/<id>` token balance edits now post an `ADJUSTMENT` `TokenTransaction` (delta through `TokenService`) instead of an absolute set with no ledger row — so `balance == Σ(TokenTransaction.amount)` holds for every user.

### Fixed
- `credit_tokens` / `debit_tokens` reject non-integral amounts with `TypeError` (previously a float silently rounded into the `Integer` column).
- Closed four direct-write bypasses of `TokenService` (core token-bundle capture/refund-restore; subscription plan-token provisioning) so every token movement is observable.

## [v26.7.0] - 2026-07-13

### Changed
- Release rollup; version bump to `26.7.0`.

## [v26.6] - 2026-06-26

### Added
- Initial tracked release tagged `v26.6`.
