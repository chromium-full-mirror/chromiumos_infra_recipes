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
MANIFEST_MOCK = """
    <manifest>
      <project path="SAMPLE" revision="FROM_REV"/>
    </manifest>
  """

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
          cwd=self.m.cros.workspace_path.join(manifest_diff.path)):
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

  def _ensure_cq_depends_fulfilled(self, from_manifest_str, to_manifest_str):
    """Checks that all CQ-DEPENDS dependencies have been met.

    Given the `from_manifest_str` and `to_manifest_str`, checks that all CLs
    that landed between the two have fulfilled CQ-DEPEND entries (ie, all
    CQ-DEPEND entries in all of those CLs exist locally in checkouts).

    Args:
      from_manifest_str (str): The from manifest XML string.
      to_manifest_str (str): The to manifest XML string.

    Returns:
      bool: True if all deps are met, False otherwise.
    """
    manifest_diffs = self.m.repo.diff_manifests(from_manifest_str,
                                                to_manifest_str)

    # Gather all CQ-DEPEND entries in all change messages.
    deps = self._gather_deps(manifest_diffs)

    # Nothing needs to be checked if there are 0 deps
    if len(deps) == 0:
      return True

    # Query Gerrit for each one of those deps to turn the CL number into a git
    # change ref.
    json_data = {
      'changes': [
        {'host': dep.host, 'change_number': dep.cl_number, 'patch_set': -1} for
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

    # Ensure each change is in the local checkout.
    for change in gerrit_results['changes']:
      if change.get('info') is None:
        results = self.m.step(
            'gerrit query failure for cl %s' % change.get('change_number'), [])
        results.presentation.status = self.m.step.WARNING
        continue
      project = change['info']['project']
      branch = change['info']['branch']
      rev = change['info']['current_revision']
      path = self.m.cros.find_project_path(project, branch)

      # Ensure that rev exists in the git repo at that path. Fail otherwise.
      with self.m.context(cwd=self.m.cros.workspace_path.join(path)):
        if not self.m.git.is_reachable(rev):
          return False

    # All the CLs in CQ-DEPEND are checkout out locally and are good to go!
    return True

  def ensure_manifest_cq_depends_fulfilled(self, from_manifest_ref,
      to_manifest_str):
    """Checks that CQ-DEPENDS deps between manifests are met.

    Checks that all CQ-DEPENDS in all CLs between `from_manifest_*` to
    `to_manifest_str` are met. Note that the from manifest is checked out from
    git at the CWD, where as the to_manifest_str is passed in by str (it is
    assumed this will be generated from a repo snapshot).

    Args:
      from_manifest_ref (str): The manifest repo ref to checkout.
      to_manifest_str (str): The string XML for the to manifest.
    """
    with self.m.step.nest('ensure manifest cq-depends fulfilled') as step:
      xml_path = self.m.context.cwd.join('snapshot.xml')
      from_xml = self.m.git.show_file(from_manifest_ref, xml_path,
                                      test_contents=MANIFEST_MOCK)

      if from_xml is None:
        step.presentation.step_text = 'skipped, no existing manifest found'
        step.presentation.status = 'WARNING'
        return

      if not self._ensure_cq_depends_fulfilled(from_xml, to_manifest_str):
        step.presentation.step_text = 'cq-depend missing locally'
        step.presentation.status = 'FAILURE'
        return

      step.presentation.step_text = 'all cq-depends fulfilled'
