# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

import re

from recipe_engine import recipe_api
from .version import Version

CHROMEOS_VERSION_PATH = 'src/third_party/chromiumos-overlay/chromeos/config/chromeos_version.sh'

CHROMEOS_VERSION_RE_MAPPING = {
    'chrome_branch': re.compile(r'\bCHROME_BRANCH=(\d+)\b'),
    'build': re.compile(r'\bCHROMEOS_BUILD=(\d+)\b'),
    'branch': re.compile(r'\bCHROMEOS_BRANCH=(\d+)\b'),
    'patch': re.compile(r'\bCHROMEOS_PATCH=(\d+)\b'),
}


class CrosVersionApi(recipe_api.RecipeApi):
  """A module for steps that manipulate Chrome OS versions."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosVersionApi, self).__init__(*args, **kwargs)
    self._remove_snapshot_from_version = properties.remove_snapshot_from_version

  Version = Version

  def read_workspace_version(self):
    """Read the Chrome OS version from the workspace.

    Returns: a Version read from the workspace.

    Raises:
      ValueError: if the version file had unexpected formatting.
    """
    test_data = ''
    test_snapshot = 0
    if self._test_data.enabled:
      test_version_str = self._test_data.get('workspace_version',
                                             self.test_api.test_version_str)
      test_data = self.test_api.chromeos_version_contents(test_version_str)
      test_version = Version.from_string(test_version_str)
      test_snapshot = test_version.snapshot or self.test_api.test_snapshot
    with self.m.step.nest('read chromeos version') as presentation:
      version_path = self.m.src_state.workspace_path.join(CHROMEOS_VERSION_PATH)
      contents = self.m.file.read_raw('read chromeos_version.sh', version_path,
                                      test_data=test_data)

      version_args = {}
      for k, regex in CHROMEOS_VERSION_RE_MAPPING.items():
        m = regex.search(contents)
        if m is None:
          raise ValueError('pattern %r did not match chromeos_version.sh' %
                           regex.pattern)
        version_args[k] = int(m.group(1))

      # This option exists because release builders need to publish artifacts
      # to specific paths (which do not include a -$snapshot suffix on the version).
      if not self._remove_snapshot_from_version:
        with self.m.step.nest('read snapshot') as read_snapshot_step:
          # If there is a snapshot in CAS, then we are running against a custom
          # manifest and there is no snapshot footer for us to read snapshot
          # numbers from. In that case we replace this piece of the version
          # with the CAS hash.
          version_snapshot = self.m.cros_source.snapshot_cas_digest
          if version_snapshot:
            read_snapshot_step.step_text = 'using snapshot from CAS'
          else:
            manifest_path = self.m.src_state.build_manifest.path
            manifest_url = self.m.src_state.build_manifest.url
            with self.m.context(cwd=manifest_path):
              snapshot = self.m.src_state.gitiles_commit.id
              self.m.git.fetch_ref(manifest_url, snapshot)
              version_snapshot = self.m.git_footers.position_num(
                  snapshot, test_position_num=test_snapshot)
          version_args['snapshot'] = version_snapshot

      version = Version(**version_args)
      presentation.step_text = 'found version: %s' % version
      return version
