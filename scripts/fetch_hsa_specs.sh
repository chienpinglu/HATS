#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="$repo_root/references/hsa/pdfs"

mkdir -p "$out_dir"

fetch_pdf() {
  local url="$1"
  local name="$2"
  local tmp="$out_dir/$name.tmp"
  local dst="$out_dir/$name"

  echo "Fetching $name"
  curl -fL "$url" -o "$tmp"
  mv "$tmp" "$dst"
}

fetch_pdf "https://hsafoundation.com/wp-content/uploads/2021/02/HSA-SysArch-1.2.pdf" "HSA-SysArch-1.2.pdf"
fetch_pdf "https://hsafoundation.com/wp-content/uploads/2021/02/HSA-PRM-1.2.pdf" "HSA-PRM-1.2.pdf"
fetch_pdf "https://hsafoundation.com/wp-content/uploads/2021/02/HSA-Runtime-1.2.pdf" "HSA-Runtime-1.2.pdf"
fetch_pdf "https://hsafoundation.com/wp-content/uploads/2021/02/cat_ModelExpressions-1.2-1.pdf" "cat_ModelExpressions-1.2-1.pdf"
fetch_pdf "https://hsafoundation.com/wp-content/uploads/2021/02/cat_Syntax-1.2.pdf" "cat_Syntax-1.2.pdf"
fetch_pdf "https://hsafoundation.com/wp-content/uploads/2021/02/cat_TestCases-1.2.pdf" "cat_TestCases-1.2.pdf"

echo "HSA specs downloaded to $out_dir"

