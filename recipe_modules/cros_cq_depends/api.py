# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for interacting with Cq-Depends."""

from collections import namedtuple
import re
from typing import List

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.repo.api import ManifestDiff
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

PRIVATE_HOST = 'chrome-internal'
PUBLIC_HOST = 'chromium'

Dep = namedtuple('Dep', ['host', 'cl_number'])


class CrosCqDependsApi(RecipeApi):
  """A module for checking that Cq-Depend has been fulfilled."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._allow_missing_depends = properties.allow_missing_depends

  def _gather_deps(self, manifest_diffs: List[ManifestDiff],
                   dep_log: List[str]) -> List[Dep]:
    """Gathers all deps from all CLs between the given manifest diffs.

    Args:
      manifest_diffs: A list of diffs to gather CLs from.
      dep_log: Human-readable output log for Milo.

    Returns:
      A list of `Dep` named tuples.
    """
    # Gather all Cq-Depend entries in all change messages.
    deps = []
    found_commits = 0
    for manifest_diff in manifest_diffs:
      # For each manifest diff, get a log of commits at that path
      with self.m.context(cwd=self.m.cros_source.workspace_path /
                          manifest_diff.path):
        git_commits = self.m.git.log(manifest_diff.from_rev,
                                     manifest_diff.to_rev)
        for commit in git_commits:
          # Accumulate Cq-Depend CLs from commits
          found_commits += 1
          dep_lines = re.findall(r'\s*Cq-Depend:\s*(.*)', commit.message,
                                 re.IGNORECASE)
          if len(dep_lines) == 0:
            continue
          # Split on white space or commas and add the dep
          for dep_line in dep_lines:
            dep_line = dep_line.strip()
            deps += re.split(r'[\s,]+', dep_line)
            dep_log.append('{} has dep_line {}'.format(commit.rev, dep_line))

    # If there are more than 50 CLs pending, automatically allow missing depends
    # so that we can get past the problem that chumped CLs cause.
    # See crbug.com/995360.
    self.m.easy.set_properties_step(found_commits=found_commits)
    self._allow_missing_depends |= found_commits > 50

    # Turn the deps into (host, cl) tuples
    valid_deps = []
    private_prefix = PRIVATE_HOST + ':'
    public_prefix = PUBLIC_HOST + ':'
    for dep in deps:
      host = ''
      change_num = ''
      if dep.startswith(public_prefix):
        host = PUBLIC_HOST
        change_num = dep[len(public_prefix):]
      if dep.startswith(private_prefix):
        host = PRIVATE_HOST
        change_num = dep[len(private_prefix):]
      if host and change_num.isdigit():
        # Only include each change once in the list.
        if Dep(host, change_num) not in valid_deps:
          dep_log.append('%s:%s' % (host, change_num))
          valid_deps.append(Dep(host, change_num))
      else:
        dep_log.append('invalid dep: %s' % dep)
    if len(valid_deps) == 0:
      dep_log.append('No Cq-Depend found in any CLs')
    return valid_deps

  def ensure_manifest_cq_depends_fulfilled(
      self, manifest_diffs: List[ManifestDiff]) -> None:
    """Checks that Cq-Depend deps between manifests are met.

    Checks that all Cq-Depend in all CLs in the given manifest diffs are met.

    Args:
      manifest_diffs: An array of `ManifestDiff` namedtuples.

    Raises:
      StepFailure: If any dependencies cannot be found on the branch, and the
        allow_missing_depends input property is False.
    """
    with self.m.step.nest('ensure manifest cq-depend fulfilled') as pres:
      # Short-circuit if the manifest didn't change.
      if len(manifest_diffs) == 0:
        pres.step_text = 'manifest did not change'
        return

      # Log the manifest diffs in human-readable form
      manifest_diff_log = pres.logs.setdefault('diff manifest', [])
      for diff in manifest_diffs:
        manifest_diff_log.append('%s upreved from %s to %s' %
                                 (diff.path, diff.from_rev, diff.to_rev))

      dep_log = pres.logs.setdefault('gather cq-depend', [])

      # Gather all Cq-Depend entries in all change messages.
      deps = self._gather_deps(manifest_diffs, dep_log)

      # Nothing needs to be checked if there are 0 deps.
      if len(deps) == 0:
        return

      # Query Gerrit for each one of those deps to turn the CL number into a git
      # change ref.
      changes = [
          GerritChange(host=dep.host, change=int(dep.cl_number)) for dep in deps
      ]
      gerrit_results = self.m.gerrit.fetch_patch_sets(changes)

      # Log dep fulfilment in human-readable format as well
      dep_local_log = pres.logs.setdefault('dep local', [])

      project_names = {p.name for p in self.m.repo.project_infos()}

      # Ensure each change is in the local checkout.
      missing_depends = []
      for change in gerrit_results:
        project = change.project
        branch = change.branch
        rev = change.current_revision
        display_id = change.display_id
        if project not in project_names:
          dep_local_log.append('change %s in non-CrOS repo %s' %
                               (display_id, project))
          continue

        paths = self.m.cros_source.find_project_paths(project, branch,
                                                      empty_ok=True)
        for path in paths:
          # Ensure that rev exists in the git repo at that path. Fail otherwise.
          with self.m.context(cwd=self.m.cros_source.workspace_path / path):

            # Check whether the dep is reachable locally.
            # If it's not, report an error, so that we
            # we can do about it.
            if not self.m.git.is_reachable(rev):
              message = (
                  'Unsatisfied dep: %s does not exist at %s on branch %s (%s)' %
                  (rev, path, branch, display_id))
              dep_local_log.append(message)
              missing_depends.append(message)

            else:
              # Dep is satisfied locally
              dep_local_log.append('%s found at %s on branch %s (%s)' %
                                   (rev, path, branch, display_id))
        if not paths:
          dep_local_log.append('Failed to find project paths (%s)' % display_id)
          continue

      if missing_depends:
        self.m.easy.set_properties_step(missing_depends=missing_depends)
        if not self._allow_missing_depends:
          raise StepFailure('\n'.join(missing_depends))

      # All deps satisfied
      pres.step_text = 'cq-depend checked'

  @staticmethod
  def get_cq_depend_reference(gerrit_change: GerritChange) -> str:
    """Return the Cq-Depend reference string for the given change.

    Args:
      gerrit_change: The change of interest.

    Returns:
      The reference string for the change, e.g. chromium:12345
    """
    match = re.match(r'(?:https://)?([^./]+)(:?-review.googlesource.com)',
                     gerrit_change.host)
    assert match, 'cannot parse short host of {}'.format(gerrit_change.host)
    return '{}:{}'.format(match.group(1), gerrit_change.change)

  def get_cq_depend(self, gerrit_changes: List[GerritChange],
                    chunk_size: int = 4) -> str:
    """Get Cq-Depend string for the given list of Gerrit changes.

    Args:
      gerrit_changes: The changes on which to depend.
      chunk_size: The number of CLs per 'Cq-Depend:' line.

    Return:
      The full Cq-Depend string.
    """
    depends = list(map(self.get_cq_depend_reference, gerrit_changes))
    chunks = []
    while depends:
      these_depends = depends[:chunk_size]
      del depends[:chunk_size]
      chunks.append('Cq-Depend: {}'.format(','.join(these_depends)))
    return '\n'.join(chunks)

  def get_mutual_cq_depend(self,
                           gerrit_changes: List[GerritChange]) -> List[str]:
    """Mutually Cq-Depend all given Gerrit changes.

    Args:
      gerrit_changes: Changes to mutually CQ-depend.

    Return:
      Cq-Depend strings in same order as changes.
    """
    return [
        self.get_cq_depend([gc
                            for gc in gerrit_changes
                            if gc != target])
        for target in gerrit_changes
    ]
