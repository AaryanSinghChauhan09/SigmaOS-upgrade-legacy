    # SigmaOS-upgrade-legacy

    Legacy upgrade path for older releases

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/mintupgrade-legacy

    ## Design principles applied
    - **Plan Before Apply**
- **Fail-Fast**
- **Defensive Programming**
- **Separation of Concerns**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `check-requirements, plan, risks, apply-plan`

    ```
    $ sigma-upgrade check-requirements --facts system.json
$ sigma-upgrade plan --packages packages.json --target 22.3
$ sigma-upgrade risks --packages packages.json
$ sigma-upgrade apply-plan --plan upgrade-plan.json           # dry-run
$ sigma-upgrade apply-plan --plan upgrade-plan.json --yes     # execute

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
