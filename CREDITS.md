# Credits and acknowledgments

`zarr-pyramid-audit` exists inside a much larger open scientific and open-source effort. This file is intentionally generous: if your work made the Vesuvius Challenge ecosystem, its data, its tools, or this repository possible, thank you.

Third-party projects named here remain under their own licenses. This acknowledgment does not relicense their code, data, models, or documentation.

## Repository lineage

- **James Ryan / sgsllc-jr** — original author of [`sgsllc-jr/zarr-pyramid-audit`](https://github.com/sgsllc-jr/zarr-pyramid-audit), the MIT-licensed upstream from which this fork descends.
- **Sven Hardy Benson / Svyable** — maintainer of this fork and its evidence-contract, gating, chunk-content, volcomp, TIFXYZ, Grand Prize preflight, and ScrolIQ-integration extensions.
- **Every contributor, issue reporter, tester, reviewer, and user** of the upstream and Svyable repositories.

## Vesuvius Challenge / Scroll Prize

Roster snapshot checked 2026-10-03 against https://scrollprize.org/. Roles change; the official site is the source of truth.

### Founders and leadership

- Nat Friedman — Instigator, Director & Founding Sponsor
- Daniel Gross — Founding Sponsor
- Brent Seales — Principal Advisor
- Giorgio Angelotti — Project & Tech Team Lead

### Tech Team

- Sean Johnson
- Hendrik Schilling
- Paul Henderson
- Elian Rafael Dal Prá
- Johannes Rudolph

### Papyrology Team

- Federica Nicolardi
- Marzia D'Angelo
- Kilian Fleischer
- Alessia Lavorante
- Michael McOsker
- Maria Chiara Robustelli
- Claudio Vergara
- Rossella Villa

### Annotation Team

- David Josey
- Kendra Brown
- Laura Trojak

### EduceLab partners

- Brent Seales
- Seth Parker
- Christy Chapman
- Mami Hayashida
- James Brusuelas
- Beth Lutin
- Roger Macfarlane

### Advisors and alumni

- JP Posma
- Stephen Parsons
- Youssef Nader
- Ben Kyles
- Julian Schilliger
- Forrest McDonald
- Adrionna Fey
- Cooper Miller
- Eric Thvedt
- Konrad Rosenberg
- Raymond Gasper
- Sarah Morejohn
- Sergei Pnev
- Techjays
- Daniel Havíř
- Ian Janicki
- Chris Frangione
- Garrett Ryan
- Dejan Gotić
- Jonny Hyman

### Papyrology advisors

- Daniel Delattre
- Gianluca Del Mastro
- Robert Fowler
- Richard Janko
- Tobias Reinhardt

### Sponsors and donors

Thank you to every named and anonymous sponsor. The current public sponsor list includes Nat Friedman, Musk Foundation, Alex Gerko, Joseph Jacks, Daniel Gross, Matt Mullenweg, John and Patrick Collison, Emergent Ventures, Eugene Jhong, Julia DeWahl and Dan Romero, Bastian Lehmann, Tobi Lutke, Arthur Breitman, Guillermo Rauch, Matt Huang, Aaron Levie, Akshay Kothari, Alexa McLain, Anjney Midha, franciscosan.org, John O'Brien, Mark Cummins, Jamie Cox and Gary Wu, Mike Mignano, Aravind Srinivas, Brandon Reeves, Brandon Silverman, Chet Corcos, Ivan Zhao, Katsuya Noguchi, Matias Nisenson, Maya and Taylor Blau, Mikhail Parakhin, Neil Parikh, Raymond Russell, Sahil Chaudhary, Shariq Hashme, Stephanie Sher, Vignan Velivela, Alex Petkas, Amjad Masad, Conor White-Sullivan, Will Fitzgerald, and the anonymous donors listed by the Challenge.

### The wider community

Thank you to every prize winner and entrant, Kaggle competitor, Discord participant, open-source maintainer, annotator, papyrologist, classicist, scanner and beamline scientist, data curator, systems engineer, reviewer, donor, volunteer, educator, and person who reported a bug or shared an experiment. The Challenge's living records of community work are:

- https://scrollprize.org/winners
- https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/20_community_projects.md

That includes the 2023 Grand Prize team and runners-up, First Letters contributors, open-source prize recipients, segmentation and ink-detection researchers, VC3D contributors, and the many people whose work is upstream of today's full-scroll pipeline.

## Open-source and standards projects used directly

- [`ScrollPrize/villa`](https://github.com/ScrollPrize/villa) — Vesuvius Challenge monorepo, including VC3D / Volume Cartographer work, the `vesuvius` library, prize metadata, website sources, segmentation, ink-detection, and supporting tooling.
- [`ScrollPrize/open-data`](https://github.com/ScrollPrize/open-data) and the Vesuvius Challenge open-data bucket — source data and catalog infrastructure used by audits and validation.
- [`superoptimizer/volume-compressor`](https://github.com/superoptimizer/volume-compressor) — MIT-licensed `volcomp` decoder vendored for read-only decoding; exact provenance is recorded in `src/zpa/data/VOLCOMP_PROVENANCE.md`.
- [`zarr-developers/zarr-python`](https://github.com/zarr-developers/zarr-python) — Zarr implementation used by chunk/surface paths.
- [`zarr-developers/numcodecs`](https://github.com/zarr-developers/numcodecs) — codec support.
- [`fsspec/filesystem_spec`](https://github.com/fsspec/filesystem_spec) and [`fsspec/s3fs`](https://github.com/fsspec/s3fs) — filesystem and S3 access.
- [`psf/requests`](https://github.com/psf/requests) — HTTP transport.
- [`numpy/numpy`](https://github.com/numpy/numpy) — numerical array operations.
- [`cgohlke/tifffile`](https://github.com/cgohlke/tifffile) and [`cgohlke/imagecodecs`](https://github.com/cgohlke/imagecodecs) — optional TIFXYZ content decoding.
- [`pytest-dev/pytest`](https://github.com/pytest-dev/pytest), [`pypa/build`](https://github.com/pypa/build), and [`pypa/setuptools`](https://github.com/pypa/setuptools) — testing and packaging.
- [`actions/checkout`](https://github.com/actions/checkout), [`actions/setup-python`](https://github.com/actions/setup-python), and [`actions/upload-artifact`](https://github.com/actions/upload-artifact) — CI plumbing.
- **OME-NGFF / OME-Zarr contributors** — the open multiscale image conventions this auditor validates against.
- **Python contributors** — the runtime and standard library underneath the project.

## Data, scanning, and institutions

Thank you to Vesuvius Challenge, EduceLab / University of Kentucky, the institutions caring for the Herculaneum papyri, the scanning facilities and beamline teams, and everyone responsible for acquiring, preserving, registering, hosting, documenting, and releasing the CT data. The Challenge's data page provides the authoritative dataset citations and licensing requirements: https://scrollprize.org/data.

## AI-assisted development

Project documentation has credited **Muse (AI assistant)** for AI-assisted development. AI-generated or AI-assisted changes remain subject to the same human review, provenance, testing, and evidence standards as any other contribution.

## If we missed you

If a person or project should be named more specifically, please open a small documentation contribution adding the missing credit. The goal of this file is not to claim ownership of community work; it is to make the dependency and gratitude chain visible.
