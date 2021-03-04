# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

import re

from recipe_engine import recipe_api
from .version import Version

CHROMIUMOS_OVERLAY_REPO = 'src/third_party/chromiumos-overlay'
CHROMEOS_VERSION_FILE = 'chromeos/config/chromeos_version.sh'
CHROMEOS_VERSION_PATH = '{}/{}'.format(CHROMIUMOS_OVERLAY_REPO,
                                       CHROMEOS_VERSION_FILE)

CHROMEOS_VERSION_RE_MAPPING = {
    'chrome_branch': re.compile(r'\bCHROME_BRANCH=(\d+)\b'),
    'build': re.compile(r'\bCHROMEOS_BUILD=(\d+)\b'),
    'branch': re.compile(r'\bCHROMEOS_BRANCH=(\d+)\b'),
    'patch': re.compile(r'\bCHROMEOS_PATCH=(\d+)\b'),
}

CHROMIUMOS_OVERLAY_REMOTE = (
    'https://chromium.googlesource.com/chromiumos/overlays/chromiumos-overlay')
# TODO(b:177902822): Update this branch to 'main' when appropriate stage of
# Rubik rollout.
CHROMIUMOS_OVERLAY_RUBIK_BRANCH = 'rubik-staging'


class CrosVersionApi(recipe_api.RecipeApi):
  """A module for steps that manipulate Chrome OS versions."""

  Version = Version

  def __init__(self, properties, *args, **kwargs):
    super(CrosVersionApi, self).__init__(*args, **kwargs)
    self._remove_snapshot_from_version = properties.remove_snapshot_from_version
    self._version_bumper_path = None
    self._version_bumper_cipd_package = (
        properties.version_bumper_cipd_package.encode('utf-8') or
        "chromiumos/infra/version_bumper/${platform}")
    # TODO(b:177902822): Set based on environment when Rubik builders hit prod.
    self._version_bumper_cipd_ref = (
        properties.version_bumper_cipd_ref.encode('utf-8') or "staging")

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

  def _ensure_version_bumper(self):
    with self.m.step.nest('ensure version_bumper'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'version_bumper')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._version_bumper_cipd_package,
                         self._version_bumper_cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._version_bumper_path = cipd_dir.join('version_bumper')

  def bump_version(self):
    """Bumps the chromeos version (as represented in chromeos_version.sh)
      and pushes the change to the chromiumos-overlay repo.

      Which component is bumped depends on the branch the invoking recipe
      is running for (main/tot --> build, release-* --> branch).

      The updated version file is currently pushed to the 'rubik-staging'
      branch of the chromiumos-overlays repo.

    Returns: None.
    """
    with self.m.step.nest('bump version'):
      old_version = self.read_workspace_version()

      # The luciexe module only makes local file changes.
      self._ensure_version_bumper()

      # This cloning logic can be removed when rubik-staging is no
      # longer in use, as the repo in the full checkout will be for
      # the correct branch.
      tmp_dir = self.m.path.mkdtemp(prefix='chromiumos-overlay')
      with self.m.context(cwd=tmp_dir):
        # Clone chromiumos-overlay repo to current path.
        with self.m.step.nest('clone chromiumos-overlay'):
          self.m.git.clone(CHROMIUMOS_OVERLAY_REMOTE,
                           branch=CHROMIUMOS_OVERLAY_RUBIK_BRANCH)

      chromiumos_overlay_repo = self.m.src_state.workspace_path.join(
          CHROMIUMOS_OVERLAY_REPO)
      # For now, overwrite to our separately cloned copy of the repo.
      chromiumos_overlay_repo = tmp_dir

      branch = self.m.cros_infra_config.config.id.branch
      component_flag = ('--bump_build_component'
                        if branch == "main" else '--bump_branch_component')
      cmd = [
          self._version_bumper_path, "bump-version",
          "--chromiumos_overlay_repo", chromiumos_overlay_repo, component_flag
      ]
      self.m.step('go version_bumper', cmd)

      # Stage, commit, and push changes.
      with self.m.context(cwd=chromiumos_overlay_repo):
        commit_lines = [
            'Update to a new version number from {}'.format(str(old_version)),
            '',
            'Generated by Rubik, see {} for job details.'.format(
                self.m.buildbucket.build_url()),
            '',
            'BUG=None',
            'TEST=None',
            '',
            'Cr-Automation-Id: release_orchestrator/version_bump',
        ]
        commit_message = '\n'.join(commit_lines)
        with self.m.step.nest('commit {}'.format(CHROMEOS_VERSION_FILE)):
          self.m.git.add([CHROMEOS_VERSION_FILE])
          self.m.git.commit(commit_message)
          self.m.git.push(
              CHROMIUMOS_OVERLAY_REMOTE,
              'HEAD:refs/heads/{}'.format(CHROMIUMOS_OVERLAY_RUBIK_BRANCH))
