# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing helpers for keyset creation and operations."""

import re
from typing import Any
from PB.chromite.api import signing
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

KEYSET_DIR_REGEX = re.compile(
    r"^([a-zA-Z0-9]+?)(MPKeys|PreMPKeys)(?:-v(\d+))?$",
    re.IGNORECASE,
)


class KeysetUtilsApi(recipe_api.RecipeApi):
  """A module to encapsulate helpers for keyset creation and operations."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def create_hsm_request(
      self,
      request: signing.CreateKeysHsmRequest,
      release_keys_path: str,
      docker_image: str,
      is_staging: bool,
      work_dir: recipe_api.Path | str,
      build_target: str = "",
      is_mp: bool | None = None,
  ) -> tuple[signing.CreateKeysHsmRequest, str | None]:
    """Prepares a CreateKeysHsmRequest for SigningService.

    Sets mandatory runtime fields (docker_image, release_keys_checkout,
    work_dir, dry_run) and calls calc_keyset_version to validate or deduce
    keyset_name.

    Args:
      request: CreateKeysHsmRequest properties passed from build input.
      release_keys_path: Path to the local release-keys repository checkout.
      docker_image: Docker image name and tag for signing operations.
      is_staging: True if running in a staging build environment.
      work_dir: Working directory path for intermediate artifacts.
      build_target: Optional build target name when keyset_name is unset.
      is_mp: Optional boolean indicating whether target keyset is MP.

    Returns:
      A tuple of (configured_request, error_message or None).
    """
    request.docker_image = docker_image
    request.release_keys_checkout = str(release_keys_path)
    request.work_dir = str(work_dir)
    # Default to dry run in staging.
    if not request.HasField("dry_run"):
      request.dry_run = is_staging

    # Default to preMP.
    is_mp = is_mp if is_mp is not None else False

    version, error_msg = self.calc_keyset_version(request, release_keys_path,
                                                  build_target=build_target,
                                                  is_mp=is_mp)
    if error_msg:
      return request, error_msg

    if not request.keyset_name and version is not None:
      request.keyset_name = self.create_keyset_name(build_target, is_mp,
                                                    version)

    with self.m.step.nest("requested keyset") as pres:
      pres.logs["keyset_name"] = str(request.keyset_name)
    return request, None

  def calc_keyset_version(
      self,
      request: signing.CreateKeysHsmRequest,
      release_keys_path: str,
      build_target: str = "",
      is_mp: bool | None = None,
  ) -> tuple[int | None, str | None]:
    """Validates explicit keyset name or calcs next version for target.

    Args:
      request: CreateKeysHsmRequest message to update.
      release_keys_path: Path to cloned release-keys repo.
      build_target: Build target name used when keyset_name is unset.
      is_mp: True for MP keys (`MPKeys`), False for PreMP.

    Returns:
      A tuple of (version or None, error_string or None).
    """
    if request.keyset_name:
      keyset_dir = release_keys_path / "keyset/public" / request.keyset_name
      if self.m.path.exists(keyset_dir):
        return None, (f"Keyset `{request.keyset_name}` already exists in "
                      "`release-keys/keyset/public`.")
      return None, None

    target = build_target
    if not target:
      return None, ("Either `keyset_name` (in `create_keys_hsm_request`) or "
                    "`build_target` (in `properties`) must be specified.")

    with self.m.step.nest("calc next keyset version"):
      max_ver = self.find_highest_keyset_version(
          release_keys_path / "keyset/public",
          target,
          is_mp,
      )
      next_ver = max_ver + 1
      return next_ver, None

  def find_highest_keyset_version(
      self,
      keyset_pub_dir: Any,
      target: str,
      is_mp: bool,
  ) -> int:
    """Finds the highest existing integer version for target in keyset_pub_dir.

    Args:
      keyset_pub_dir: Path object for release-keys/keyset/public.
      target: Base build target name (e.g., 'atlas').
      is_mp: True if searching for MP keys (`MPKeys`), False for PreMP.

    Returns:
      Highest integer version found, or 0 if no matching directory exists.
    """
    found_paths = self.m.file.listdir("list existing keysets", keyset_pub_dir)
    max_ver = 0
    expected_suffix_lower = "mpkeys" if is_mp else "prempkeys"

    for p in found_paths:
      dirname = self.m.path.basename(p)
      m = KEYSET_DIR_REGEX.match(dirname)
      if (m and m.group(1).lower() == target.lower() and
          m.group(2).lower() == expected_suffix_lower):
        # v1 suffix is omitted.
        ver = int(m.group(3)) if m.group(3) else 1
        max_ver = max(max_ver, ver)
    return max_ver

  def create_keyset_name(
      self,
      target: str,
      is_mp: bool,
      next_ver: int,
  ) -> str:
    """Formats standard keyset name given target, MP status, and version.

    Args:
      target: Base build target name.
      is_mp: True if MP keyset, False if PreMP keyset.
      next_ver: Integer version to format (`1` omits suffix).

    Returns:
      Formatted keyset directory name string.
    """
    ver_suffix = "" if next_ver == 1 else f"-v{next_ver}"
    key_type = "MPKeys" if is_mp else "PreMPKeys"
    return f"{target[0].upper()}{target[1:]}{key_type}{ver_suffix}"

  def stage_quorum_inbox(
      self,
      work_keyset_dir: recipe_api.Path,
      inbox_dir: recipe_api.Path,
      artifacts_to_stage: list[str],
  ) -> list[recipe_api.Path]:
    """Stages quorum ceremony artifacts into a local directory.

    Args:
      work_keyset_dir: Directory containing intermediate keyset artifacts.
      inbox_dir: Destination directory to stage quorum inbox artifacts.
      artifacts_to_stage: Artifact file names to stage.

    Returns:
      List of destination Paths copied into inbox_dir.
    """
    with self.m.step.nest("stage quorum inbox") as pres:
      if not artifacts_to_stage:
        raise StepFailure(
            "Quorum inbox staging failed: no artifacts specified to stage.")

      self.m.file.ensure_directory("ensure quorum inbox directory", inbox_dir)
      workdir_paths = self.m.file.listdir(
          "discover quorum inbox artifacts",
          work_keyset_dir,
      )
      artifact_filenames = {self.m.path.basename(p) for p in workdir_paths}
      pres.logs["found_artifacts"] = sorted(artifact_filenames)

      to_stage = [a for a in artifacts_to_stage if a in artifact_filenames]
      missing_artifacts = [
          a for a in artifacts_to_stage if a not in artifact_filenames
      ]

      missing_artifact_str = ""
      if missing_artifacts:
        missing_artifact_str = f"\nmissing {len(missing_artifacts)} artifact(s)"
        pres.logs["missing_artifacts"] = [
            self.m.path.basename(a) for a in missing_artifacts
        ]

      if not to_stage:
        raise StepFailure(
            "Quorum inbox staging failed: none of the specified artifacts were found."
        )

      staged_paths = []
      for artifact in to_stage:
        dest_path = inbox_dir / artifact
        self.m.file.copy(f"stage {artifact}", work_keyset_dir / artifact,
                         dest_path)
        staged_paths.append(dest_path)

      pres.step_text = f"staged {len(staged_paths)} artifact(s){missing_artifact_str}"
      pres.logs["staged_artifacts"] = [
          self.m.path.basename(p) for p in staged_paths
      ]
      return staged_paths
