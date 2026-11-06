from __future__ import annotations

import stage_project


stage_project.H11 = stage_project.ROOT / "review" / "H11" / "attempt2"
stage_project.PROJECT = stage_project.H11 / "runtime" / "project"


if __name__ == "__main__":
    stage_project.main()
