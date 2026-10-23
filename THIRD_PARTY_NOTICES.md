# Third-party components and attribution

The MIT license in [LICENSE](LICENSE) covers the project material that the
copyright holder is entitled to license. It does not relicense third-party
software, market data, trademarks, or material outside that grant.

No dependency source code, binary library, market-data corpus, or third-party
artwork is vendored in this source snapshot. Python dependencies are installed
separately from their distributions, which retain their license/copyright files.
Do not remove those notices when redistributing dependency distributions.

## Runtime dependencies examined

| Distribution | Pinned version | License declared by distribution metadata |
| --- | --- | --- |
| pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| pydantic_core | 2.46.5 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| annotated-types | 0.8.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |

The dependency metadata and associated license files, not this summary, govern
those packages. Their authors retain their copyright. Version constraints are
listed in `constraints.txt`; dependency installation is not bundling their source
into this repository or assigning their authorship to the GridBot author.

## Development and build tools

pytest, Ruff, Mypy, pre-commit, Hatchling and other development tools retain their
own terms. Examined metadata includes MIT, BSD, Apache-2.0, MPL-2.0 and PSF-2.0.
Hypothesis and pathspec use MPL-2.0; they are separate installed tools, not source
copied into the project. The MIT grant does not override obligations if a future
release redistributes third-party code, binaries or modifications to such code.
Recheck licenses before adding vendored components or external datasets.

## Data, provenance and assistance

The runnable public examples generate explicitly fictional candles in memory;
the test suite uses small constructed fixtures. No rights to official Binance
market-data archives are granted or claimed by this MIT license, and no archive
corpus is included. Research summaries describe hypothetical accounts, not the
author's personal holdings. The source manifest identifies the curated snapshot.

Leonardo Siqueira Ribeiro dos Santos directs the project. AI assistants helped
with implementation, tests, documentation and review, as disclosed in the README.
That assistance is not presented as an independent certified audit or as exclusive
authorship of third-party material. Preserve attribution when adding contributions.
