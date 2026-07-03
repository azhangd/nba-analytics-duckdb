"""Optional dependency checks for heavyweight pipeline features."""

from importlib.util import find_spec

OPTIONAL_GROUPS = {
    "ml": {
        "joblib": "joblib",
        "scipy": "scipy",
        "sklearn": "scikit-learn",
        "umap": "umap-learn",
        "xgboost": "xgboost",
    },
    "live": {
        "nba_api": "nba-api",
        "pdfplumber": "pdfplumber",
    },
}


class MissingOptionalDependencyError(RuntimeError):
    """Raised when a command needs an optional dependency group."""

    def __init__(
        self,
        *,
        groups: tuple[str, ...],
        missing_modules: tuple[str, ...],
        missing_packages: tuple[str, ...],
        hint: str,
        install_command: str,
        pip_install_command: str,
        quick_command: str | None = None,
    ) -> None:
        self.groups = groups
        self.missing_modules = missing_modules
        self.missing_packages = missing_packages
        self.hint = hint
        self.install_command = install_command
        self.pip_install_command = pip_install_command
        self.quick_command = quick_command
        super().__init__(str(self))

    def __str__(self) -> str:
        group_names = ", ".join(self.groups)
        modules = ", ".join(self.missing_modules)
        return (
            f"Missing optional dependency group(s): {group_names}. "
            f"Missing module(s): {modules}. {self.hint}"
        )


class MissingRequiredDependencyError(RuntimeError):
    """Raised when a required runtime dependency is missing from the install."""

    def __init__(
        self,
        *,
        missing_modules: tuple[str, ...],
        missing_packages: tuple[str, ...],
        hint: str,
        install_command: str,
        pip_install_command: str,
    ) -> None:
        self.missing_modules = missing_modules
        self.missing_packages = missing_packages
        self.hint = hint
        self.install_command = install_command
        self.pip_install_command = pip_install_command
        super().__init__(str(self))

    def __str__(self) -> str:
        modules = ", ".join(self.missing_modules)
        return f"Missing required module(s): {modules}. {self.hint}"


def missing_modules_for_groups(*groups: str) -> dict[str, str]:
    missing = {}
    for group in groups:
        modules = OPTIONAL_GROUPS.get(group)
        if modules is None:
            raise ValueError(f"Unknown optional dependency group: {group}")
        for module_name, package_name in modules.items():
            if find_spec(module_name) is None:
                missing[module_name] = package_name
    return dict(sorted(missing.items()))


def require_optional_groups(
    *groups: str,
    hint: str,
    install_command: str,
    pip_install_command: str,
    quick_command: str | None = None,
) -> None:
    missing = {}
    missing_groups = []
    for group in groups:
        group_missing = missing_modules_for_groups(group)
        if group_missing:
            missing_groups.append(group)
            missing.update(group_missing)

    if not missing:
        return
    raise MissingOptionalDependencyError(
        groups=tuple(missing_groups),
        missing_modules=tuple(missing),
        missing_packages=tuple(dict.fromkeys(missing.values())),
        hint=hint,
        install_command=install_command,
        pip_install_command=pip_install_command,
        quick_command=quick_command,
    )
