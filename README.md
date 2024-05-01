# Factory Data — retired

This application has been merged into the **factory station**:

> <https://github.com/soccentric-stm32/factory-station>

The station now owns the whole flow: detect, load BOOT and the factory
firmware, generate the `.sys`, `.cal` and `.diag` files from CSV, write them
to the board, validate, and track everything in the artifacts repository.
The Qt-free core (`paths`, `fileformat`, `generators`, `rules`, `units`,
`batch`, `workspace`, `service`, `capi`) and the command line moved there.

The CLI keeps the same commands and exit codes:

```bash
hwval-factory-data check sys  csv/sys.csv
hwval-factory-data generate cal csv/cal.csv --out out
hwval-factory-data verify out
hwval-factory-data inspect out/SC0001.sys
```

The source in this repository is kept for history only; do not add new
features here.  Open changes against `factory-station` instead.
