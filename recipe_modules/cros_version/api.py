# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

import datetime
import re

from recipe_engine.recipe_api import RecipeApi, StepFailure
from RECIPE_MODULES.chromeos.cros_version.version import Version
from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

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


class CrosVersionApi(RecipeApi):
  """A module for steps that manipulate CrOS versions."""

  Version = Version

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._remove_snapshot_from_version = properties.remove_snapshot_from_version
    self._properties = properties
    self._version = None

  @property
  def version(self):
    """The Version of the workspace checkout."""
    return self._version or self.read_workspace_version()

  def read_workspace_version(self, name='read chromeos version'):
    """Read the CrOS version from the workspace.

    Returns: a Version read from the workspace.

    Args:
      name (str): The name to use for the step.

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
    with self.m.step.nest(name) as presentation:
      version_path = self.m.src_state.workspace_path.join(CHROMEOS_VERSION_PATH)
      contents = self.m.file.read_text('read chromeos_version.sh', version_path,
                                       test_data=test_data, include_log=False)

      version_args = {}
      for k, regex in CHROMEOS_VERSION_RE_MAPPING.items():
        m = regex.search(contents)
        if m is None:
          raise ValueError('pattern %r did not match chromeos_version.sh' %
                           regex.pattern)
        version_args[k] = int(m.group(1))

      # This option exists because release builders need to publish artifacts
      # to specific paths (which do not include a -$snapshot suffix on the
      # version).
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
      self._version = version
      presentation.step_text = 'found version: %s' % version
      return version

  def _reset_to_remote(self, branch):
    """Reset to the remote branch."""
    self.m.git.fetch_refs('cros', branch)
    self.m.step('reset to remote branch',
                ['git', 'reset', '--hard', 'cros/{}'.format(branch)])

  @exponential_retry(retries=3, delay=datetime.timedelta(minutes=2))
  def _check_version(self, branch, expected_version):
    with self.m.step.nest('check version change reflected on remote'):
      # Reset to the remote branch.
      # We need to do this so that the local checkout has the correct SHA
      # for the version bump SHA (gerrit.create_change will push the local
      # change to a different SHA on the remote even if we're on the correct
      # branch).
      self._reset_to_remote(branch)
      version = self.read_workspace_version(name='read remote version')
      if version != expected_version:
        raise StepFailure('version bump not reflected on remote')

  def bump_version(self, dry_run=True, use_local_diff=False):
    """Bumps the chromeos version (as represented in chromeos_version.sh)
      and pushes the change to the chromiumos-overlay repo.

      Which component is bumped depends on the branch the invoking recipe
      is running for (main/tot --> build, release-* --> branch).

      Args:
        dry_run (bool): Whether the git push is --dry-run.
        use_local_diff (bool): If true, use the local diff instead of diff
          taken against tip-of-branch for the version bump CL.
    """
    with self.m.step.nest('bump version') as pres:
      if self.m.cq.active and not dry_run:
        raise StepFailure('CQ must set dry_run')

      overlay_path = self.m.src_state.workspace_path.join(
          CHROMIUMOS_OVERLAY_REPO)

      with self.m.context(cwd=overlay_path):
        # By default, we push to the manifest branch.
        push_branch = self.m.cros_source.manifest_push
        self.m.git.checkout(push_branch)

        cmd = [
            'bump-version',
            '--chromiumos_overlay_repo',
            overlay_path,
            '--bump_from_branch_name',
            self.m.cros_source.manifest_push,
        ]
        self.m.gobin.call('version_bumper', cmd)

        # Update the version in output properties.
        new_version = self.read_workspace_version(name='read updated version')
        self.m.easy.set_properties_step(
            chromeos_version=str(new_version),
            full_version=new_version.legacy_version)

        # Stage, commit, and push changes.
        commit_lines = [
            'Increment to version {}'.format(str(new_version)),
            '',
            'Generated by {}.'.format(self.m.buildbucket.build.builder.builder),
            '',
            'Cr-Build-Url: {}'.format(self.m.buildbucket.build_url()),
            'Cr-Automation-Id: cros_version/bump_version',
        ]
        commit_message = '\n'.join(commit_lines)
        with self.m.step.nest('commit {}'.format(CHROMEOS_VERSION_FILE)):
          self.m.git.add([CHROMEOS_VERSION_FILE])
          self.m.git.commit(commit_message)
          # Have to manually set the upstream here or `git cl` will fail.
          # See crbug/1288910 for context.
          self.m.git.set_upstream('cros', push_branch)
          change = None
          try:
            change = self.m.gerrit.create_change(
                'chromiumos/overlays/chromiumos-overlay',
                ref=self.m.git.get_branch_ref(push_branch),
                project_path=overlay_path, use_local_diff=use_local_diff)
          except StepFailure as e:
            if dry_run:
              pres.step_text = 'Could not `git push`. Ignoring as this is a dry-run.'
            else:
              raise e
          if change:
            if dry_run:
              pres.step_text = 'dry-run only'
              self.m.gerrit.abandon_change(change, message='dry-run only')
            else:
              labels = {
                  Label.BOT_COMMIT: 1,
                  Label.VERIFIED: 1,
              }
              self.m.gerrit.set_change_labels_remote(change, labels)
              self.m.gerrit.submit_change(change, project_path=overlay_path)

          if not dry_run:
            self._check_version(push_branch, new_version)
          else:
            # If staging, need to blow away the version bump so that buildspecs
            # contain SHAs that are valid on the remote.
            self._reset_to_remote(push_branch)
