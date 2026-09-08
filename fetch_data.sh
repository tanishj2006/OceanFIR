#!/usr/bin/env bash
# Downloads the AIS day file the pipeline needs. ~341 MB zipped, ~1.5 GB
# unzipped. It is gitignored on purpose — do not commit it.
#
#   ./fetch_data.sh
set -e
cd "$(dirname "$0")/data"
if [ -f AIS_2023_06_20.csv ]; then echo "already have AIS_2023_06_20.csv"; exit 0; fi
echo "downloading MarineCadastre AIS 2023-06-20 (~341 MB) ..."
# -L is required. Without it you get a 248-byte redirect stub, not the zip.
# 2023 is the newest working year; the 2024 folder exists but its files 404.
curl -L -o AIS_2023_06_20.zip \
  "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/AIS_2023_06_20.zip"
unzip -o AIS_2023_06_20.zip && rm -f AIS_2023_06_20.zip
echo "done: $(ls -lh AIS_2023_06_20.csv | awk '{print $5}')"
