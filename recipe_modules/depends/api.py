# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for checking that CQ-DEPEND has been fulfilled."""
import re
from collections import namedtuple

from recipe_engine import recipe_api

PRIVATE_HOST = 'chrome-internal'
PUBLIC_HOST = 'chromium'

Dep = namedtuple('Dep', ['host', 'cl_number'])


class DependsApi(recipe_api.RecipeApi):
  """A module for checking that CQ-DEPEND has been fulfilled."""

  def _gather_deps(self, manifest_diffs):
    """Gathers all deps from all CLs between the given manifest diffs.

    Args:
      manifest_diffs (List[ManifestDiff]): An array of `ManifestDiff`.

    Returns:
      List[Dep]: A list of `Dep` named tuples.
    """
    # Gather all CQ-DEPEND entries in all change messages.
    deps = []
    for manifest_diff in manifest_diffs:
      # For each manifest diff, get a log of commits at that path
      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(manifest_diff.path)):
        git_commits = self.m.git.log(manifest_diff.from_rev,
                                     manifest_diff.to_rev)
        for commit in git_commits:
          # Accumulate CQ-DEPEND CLs from commits
          dep_lines = re.findall(r'^\s*CQ-DEPEND=(.*)$', commit.message,
                                 re.IGNORECASE)
          if len(dep_lines) == 0:
            continue
          # Split on white space or commas and add the dep
          for dep_line in dep_lines:
            deps += re.split(r'[\s,]+', dep_line)
    # Turn the deps into (host, cl) tuples
    public = [Dep(PUBLIC_HOST, dep) for dep in deps if not dep.startswith('*')]
    private = [Dep(PRIVATE_HOST, dep[1:]) for dep in deps if
               dep.startswith('*')]
    return public + private

  def ensure_manifest_cq_depends_fulfilled(self, manifest_diffs):
    """Checks that CQ-DEPENDS deps between manifests are met.

    Checks that all CQ-DEPENDS in all CLs in the given manifest diffs are met.

    Args:
      manifest_diffs (List[ManifestDiff]): An array of `ManifestDiff`
          namedtuples.
    """
    with self.m.step.nest('ensure manifest cq-depends fulfilled') as step:
      # Short-circuit if the manifest didn't change.
      if len(manifest_diffs) == 0:
        step.presentation.step_text = 'manifest did not change'
        return

      # Log the manifest diffs in human-readable form
      manifest_diff_log = step.presentation.logs.setdefault('diff manifest', [])
      for diff in manifest_diffs:
        manifest_diff_log.append(
            '%s upreved from %s to %s' % (
            diff.path, diff.from_rev, diff.to_rev))

      # Gather all CQ-DEPEND entries in all change messages.
      deps = self._gather_deps(manifest_diffs)

      dep_log = step.presentation.logs.setdefault('gather cq-depend', [])

      # Nothing needs to be checked if there are 0 deps.
      if len(deps) == 0:
        dep_log.append('No CQ-DEPEND found in any CLs')
        return

      for dep in deps:
        dep_log.append('CL:%s on %s' % (dep.cl_number, dep.host))

      # Query Gerrit for each one of those deps to turn the CL number into a git
      # change ref.
      json_data = {
        'changes': [
          {'host': dep.host, 'change_number': dep.cl_number, 'patch_set': -1}
          for
          dep in deps]}
      test_data = {
        'changes': [{
          'info': {
            'project': 'PROJECT',
            'branch': 'BRANCH',
            'current_revision': 'CURRENT_REVISION',
          }
        }, {'change_number': 1234, 'info': None}]
      }
      gerrit_results = self.m.support.call('gerrit-fetch-changes', json_data,
                                           test_output_data=test_data)

      # Log dep fulfilment in human-readable format as well
      dep_local_log = step.presentation.logs.setdefault('dep local', [])

      # Ensure each change is in the local checkout.
      for change in gerrit_results['changes']:
        if change.get('info') is None:
          dep_local_log.append(
            'gerrit query failure for cl %s' % change.get('change_number'))
          step.presentation.status = self.m.step.WARNING
          continue
        project = change['info']['project']
        branch = change['info']['branch']
        rev = change['info']['current_revision']
        path = self.m.cros_source.find_project_path(project, branch)

        # Ensure that rev exists in the git repo at that path. Fail otherwise.
        with self.m.context(cwd=self.m.cros_source.workspace_path.join(path)):

          # Ensure the dep is reachable locally
          if not self.m.git.is_reachable(rev):
            dep_local_log.append(
              'Unsatisfied dep! %s does not exist at %s on branch %s' % (
              rev, path, branch))
            step.presentation.step_text = 'cq-depend missing locally'
            step.presentation.status = 'FAILURE'
            return

          # Dep is satisfied locally
          dep_local_log.append(
            '%s found at %s on branch %s' % (rev, path, branch))

      # All deps satisfied
      step.presentation.step_text = 'all cq-depends fulfilled'
