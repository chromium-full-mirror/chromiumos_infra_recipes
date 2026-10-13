# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Records per-target firmware build configs in Cloud Spanner."""

from collections.abc import Mapping
import dataclasses
import datetime
import re
from typing import Any

from recipe_engine import config_types
from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts

# The tarballs that hold the firmware images of a target. An EC target has
# krabby.EC.tar.bz2 or krabby.EC.16640.2.39.tar.bz2, but not krabby.EC_elf.*. An
# AP target has grogu.16849.0.0.tar.bz2 with its image, but not the source and
# the logs of a baseboard, such as atria/firmware_from_source.tar.bz2.
_EC_TARBALL_RE = re.compile(
    r'^(.+?)\.(?:EC(?:\.[^/]+)?\.tar\.bz2|firmware\.tbz2)$')
_AP_TARBALL_RE = re.compile(r'^([^./]+)\.\d[\d.]*\.tar\.bz2$')
_CONFIG_PATH_RE = re.compile(r'^configs/([^/]+)/([^/]+)\.(?:config|json)$')
_SPANNER_SCOPE = 'https://www.googleapis.com/auth/spanner.data'


@dataclasses.dataclass
class _TargetFiles:
  """The exported config files of one (platform, target) pair."""

  configs: dict[str, str] = dataclasses.field(default_factory=dict)
  components_path: str | None = None


class FirmwareConfigApi(recipe_api.RecipeApi):
  """API for publishing per-target firmware configs to Cloud Spanner."""

  def publish(
      self,
      uploaded_artifacts: UploadedArtifacts,
      artifact_dir: config_types.Path,
      metadata_by_name: Mapping[str, Any],
      start_time: datetime.datetime,
  ) -> None:
    """Records the Kconfig and Devicetree configs of the firmware targets built.

    They go to a Cloud Spanner database that can be queried across builds
    (b/571108483, schema in resources/schema.sql).

    Args:
      uploaded_artifacts: Artifacts uploaded by BundleFirmwareArtifacts.
      artifact_dir: Directory where the bundled files reside on disk.
      metadata_by_name: Map from relative artifact file name to its
        TarballInfo or ConfigInfo protobuf message.
      start_time: UTC timestamp when the build started.
    """
    uri_by_target: dict[str, str] = {}
    boards_by_target: dict[str, list[str]] = {}
    for name in uploaded_artifacts.files_by_artifact.get(
        'FIRMWARE_TARBALL', []):
      match = _EC_TARBALL_RE.match(name) or _AP_TARBALL_RE.match(name)
      if not match:
        continue
      target = match.group(1)
      uri_by_target[target] = (f'gs://{uploaded_artifacts.gs_bucket}/'
                               f'{uploaded_artifacts.gs_path}/{name}')
      info = metadata_by_name.get(name)
      if info and info.board:
        boards_by_target[target] = list(info.board)

    grouped: dict[tuple[str, str], _TargetFiles] = {}
    config_files = [
        *uploaded_artifacts.files_by_artifact.get('FIRMWARE_CONFIG', []),
        *uploaded_artifacts.files_by_artifact.get('FIRMWARE_TARBALL_INFO', []),
    ]
    for name in config_files:
      match = _CONFIG_PATH_RE.match(name)
      info = metadata_by_name.get(name)
      target = getattr(info, 'target', '') or (match.group(1) if match else '')
      kind = getattr(info, 'kind', '') or (match.group(2) if match else '')
      if not target or not kind:
        continue
      boards = (
          list(info.board) if info and info.board else boards_by_target.get(
              target, []))
      path = str(self.m.path.abspath(self.m.path.join(artifact_dir, name)))
      for board in boards or ['']:
        entry = grouped.setdefault((board, target), _TargetFiles())
        if kind == 'components':
          entry.components_path = path
        else:
          entry.configs[kind] = path

    if not grouped:
      return

    targets = [{
        'platform': board,
        'target': target,
        'uri': uri_by_target.get(target),
        'configs': dict(sorted(entry.configs.items())),
        'components_path': entry.components_path,
    } for (board, target), entry in sorted(grouped.items())]

    build = self.m.buildbucket.build
    commit = self.m.src_state.gitiles_commit
    version = self.m.cros_version.version
    data = {
        'database': ('build_metadata_staging' if
                     self.m.cros_infra_config.is_staging else 'build_metadata'),
        'build': {
            'id': build.id,
            'builder': build.builder.builder,
            'bucket': build.builder.bucket,
            'number': build.number,
            'start_time': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'branch': commit.ref.removeprefix('refs/heads/'),
            'commit': commit.id,
            'milestone': version.milestone,
            'platform_version': version.platform_version,
        },
        'targets': targets,
    }
    with self.m.step.nest('publish target configs') as pres:
      pres.logs['input'] = self.m.json.dumps(data, indent=2, sort_keys=True)
      token = self.m.service_account.default().get_access_token(
          [_SPANNER_SCOPE])
      self.m.step(
          'write rows',
          [
              self.resource('publish_target_configs.py'),
              '--token-file',
              self.m.raw_io.input_text(token),
              '--input-json',
              self.m.json.input(data),
          ],
          timeout=10 * 60,
      )
