# Report figures

Generate all figures from the committed machine-readable summaries with:

```bash
python3 -m analysis.generate_report_figures
```

The script writes both 300-DPI PNG files for the report and SVG files for
lossless editing. Figure numbering follows the recommended order in the final
report:

1. consistency violation matrix across S0-S4;
2. transition-window consistency and availability;
3. election, replication-lag, and recovery timing; and
4. detailed S4 violation rates by client-centric model.
