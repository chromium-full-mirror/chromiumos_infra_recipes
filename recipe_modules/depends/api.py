# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for checking that Cq-Depend has been fulfilled."""
import re
from collections import namedtuple

from recipe_engine import recipe_api

PRIVATE_HOST = 'chrome-internal'
PUBLIC_HOST = 'chromium'

Dep = namedtuple('Dep', ['host', 'cl_number'])


class DependsApi(recipe_api.RecipeApi):
  """A module for checking that Cq-Depend has been fulfilled."""

  def _gather_deps(self, manifest_diffs):
    """Gathers all deps from all CLs between the given manifest diffs.

    Args:
      manifest_diffs (List[ManifestDiff]): An array of `ManifestDiff`.

    Returns:
      List[Dep]: A list of `Dep` named tuples.
    """
    # Gather all Cq-Depend entries in all change messages.
    deps = []
    for manifest_diff in manifest_diffs:
      # For each manifest diff, get a log of commits at that path
      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(manifest_diff.path)):
        git_commits = self.m.git.log(manifest_diff.from_rev,
                                     manifest_diff.to_rev)
        for commit in git_commits:
          # Accumulate Cq-Depend CLs from commits
          dep_lines = re.findall(r'\s*Cq-Depend:(.*)', commit.message,
                                 re.IGNORECASE)
          if len(dep_lines) == 0:
            continue
          # Split on white space or commas and add the dep
          for dep_line in dep_lines:
            deps += re.split(r'[\s,]+', dep_line)
    # Turn the deps into (host, cl) tuples
    valid_deps = []
    private_prefix = PRIVATE_HOST + ':'
    public_prefix = PUBLIC_HOST + ':'
    for dep in deps:
      host = ""
      change_num = ""
      if dep.startswith(public_prefix):
        host = PUBLIC_HOST
        change_num = dep[len(public_prefix):]
      if dep.startswith(private_prefix):
        host = PRIVATE_HOST
        change_num = dep[len(private_prefix):]
      if host and change_num.isdigit():
        valid_deps.append(Dep(host, change_num))
    return valid_deps

  def ensure_manifest_cq_depends_fulfilled(self, manifest_diffs):
    """Checks that Cq-Depend deps between manifests are met.

    Checks that all Cq-Depend in all CLs in the given manifest diffs are met.

    Args:
      manifest_diffs (List[ManifestDiff]): An array of `ManifestDiff`
          namedtuples.
    """
    with self.m.step.nest('ensure manifest cq-depend fulfilled') as step:
      # Short-circuit if the manifest didn't change.
      if len(manifest_diffs) == 0:
        step.presentation.step_text = 'manifest did not change'
        return

      # Log the manifest diffs in human-readable form
      manifest_diff_log = step.presentation.logs.setdefault('diff manifest', [])
      for diff in manifest_diffs:
        manifest_diff_log.append('%s upreved from %s to %s' %
                                 (diff.path, diff.from_rev, diff.to_rev))

      # Gather all Cq-Depend entries in all change messages.
      deps = self._gather_deps(manifest_diffs)

      dep_log = step.presentation.logs.setdefault('gather cq-depend', [])

      # Nothing needs to be checked if there are 0 deps.
      if len(deps) == 0:
        dep_log.append('No Cq-Depend found in any CLs')
        return

      for dep in deps:
        dep_log.append('CL:%s on %s' % (dep.cl_number, dep.host))

      # Query Gerrit for each one of those deps to turn the CL number into a git
      # change ref.
      json_data = {
          'changes': [{
              'host': dep.host,
              'change_number': int(dep.cl_number),
              'patch_set': -1
          } for dep in deps]
      }
      test_data = {
          'changes': [
            {
              'info': {
                  # This project name corresponds to a repo test_data project.
                  'project': 'c',
                  'branch': 'master',
                  'current_revision': 'deadbeef',
              },
            },
            {
              'info': {
                  # Imitates a project outside the chromiumos checkout.
                  'project': 'not-a-project',
                  'branch': 'master',
                  'current_revision': 'deadbeef',
              },
            },
            {
              'change_number': 1234,
              'info': None,
            },
          ]
      }
      gerrit_results = self.m.support.call('gerrit-fetch-changes', json_data,
                                           test_output_data=test_data)

      # Log dep fulfilment in human-readable format as well
      dep_local_log = step.presentation.logs.setdefault('dep local', [])

      project_names = {p.name for p in self.m.repo.project_infos()}

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
        if project not in project_names:
          dep_local_log.append('change %s in non-Chrome OS repo %s' %
                               (change.get('change_number'), project))
          continue
        path = self.m.cros_source.find_project_path(project, branch)

        # Ensure that rev exists in the git repo at that path. Fail otherwise.
        with self.m.context(cwd=self.m.cros_source.workspace_path.join(path)):

          # Ensure the dep is reachable locally
          if not self.m.git.is_reachable(rev):
            dep_local_log.append(
                'Unsatisfied dep! %s does not exist at %s on branch %s' %
                (rev, path, branch))
            step.presentation.status = self.m.step.FAILURE
            raise self.m.step.StepFailure('cq-depend missing locally')

          # Dep is satisfied locally
          dep_local_log.append(
              '%s found at %s on branch %s' % (rev, path, branch))

      # All deps satisfied
      step.presentation.step_text = 'all cq-depends fulfilled'
