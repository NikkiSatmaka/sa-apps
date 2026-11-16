# Deployment guide

The authoritative deployment, backup/restore, migration compatibility, rollback, smoke-check, and operational ownership guidance is maintained in the repository-root [`deployment.md`](../deployment.md), alongside the production `compose.yaml` configuration.

This file intentionally does not duplicate deployment commands: use the root guide so procedures remain aligned with the image-based Compose deployment and its fail-closed `backend-init` migration dependency. Historical MVP deployment instructions are obsolete and must not be used for current operations.
