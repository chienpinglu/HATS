# HSA References

This directory tracks the HSA sources that inform HATS. The public GitHub
repository keeps an index and fetch script rather than committing the PDFs
directly, because the HSA specification PDFs include redistribution language.

Run the fetch script from the repository root to download local copies:

```sh
scripts/fetch_hsa_specs.sh
```

Downloaded files are placed in `references/hsa/pdfs/`, which is ignored by Git.

## Version 1.2 Core Specifications

- HSA Platform System Architecture Specification 1.2
  - Source: https://hsafoundation.com/wp-content/uploads/2021/02/HSA-SysArch-1.2.pdf
  - HATS relevance: shared virtual memory, cache coherency, signals,
    user-mode queues, AQL packets, scheduling, profiling, and the HSA memory
    model.
- HSA Programmer's Reference Manual Specification 1.2
  - Source: https://hsafoundation.com/wp-content/uploads/2021/02/HSA-PRM-1.2.pdf
  - HATS relevance: HSAIL, the programming model, compiler-facing semantics,
    finalization, BRIG, memory segments, and signal operations.
- HSA Runtime Programmer's Reference Specification 1.2
  - Source: https://hsafoundation.com/wp-content/uploads/2021/02/HSA-Runtime-1.2.pdf
  - HATS relevance: agent discovery, queue creation, AQL dispatch, signals,
    memory management, executable loading, and profiling APIs.

## Formal Memory Model

- Towards a Formalization of the HSA Memory Model in the cat Language 1.2
  - Source: https://hsafoundation.com/wp-content/uploads/2021/02/cat_ModelExpressions-1.2-1.pdf
- Syntax and Semantics of the cat Language 1.2
  - Source: https://hsafoundation.com/wp-content/uploads/2021/02/cat_Syntax-1.2.pdf
- Representative Litmus Tests 1.2
  - Source: https://hsafoundation.com/wp-content/uploads/2021/02/cat_TestCases-1.2.pdf

The official standards index is:

https://hsafoundation.com/standards/

