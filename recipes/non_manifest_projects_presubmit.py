# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running presubmit on CLs for projects not in the manifest."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.presubmit_tests import PresubmitTestsProperties

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'bot_cost',
    'cros_source',
    'gerrit',
    'git',
]


EXTERNAL_REVIEW_HOST = 'chromium-review.googlesource.com'
INTERNAL_REVIEW_HOST = 'chrome-internal-review.googlesource.com'

EXTERNAL_HOST_REPO_TEMPLATE = 'https://chromium.googlesource.com/%s'
INTERNAL_HOST_REPO_TEMPLATE = 'https://chrome-internal.googlesource.com/%s'

PROPERTIES = PresubmitTestsProperties


def RunSteps(api, properties):
  with api.bot_cost.build_cost_context():
    project_to_patches_map = categorize_changes(
        api, properties, api.buildbucket.build.input.gerrit_changes)
    for project, patch_sets in sorted(project_to_patches_map.items()):
      apply_changes_and_run_presubmits(api, project, patch_sets)


def categorize_changes(api, properties, gerrit_changes):
  """Group changes by Gerrit project.

  Groups changes by Gerrit project and discards any changes to Gerrit projects
  not support by the builder as specified in the "projects" input property.

  Args:
    properties (PresubmitTestProperties): Build input properties.
    gerrit_changes (list[GerritChange]): The Gerrit changes passed in to the
        build from CQ.

  Returns:
    project_to_patchest_map (dict{str:list[PatchSet]}): Dict mapping the name of
        the Gerrit project to a list of relevant PatchSets.
  """

  with api.step.nest('validate inputs') as presentation:
    # If there are no gerrit_changes, we're done.
    if not gerrit_changes:
      presentation.step_text = 'No changes given:  Build is POINTLESS.'

    patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)

    project_to_patches_map = {}
    dropped_changes = []

    for p in patch_sets:
      if p.project not in properties.project_names:
        dropped_changes.append(p.display_id)
        continue
      if p.project not in project_to_patches_map:
        project_to_patches_map[p.project] = []
      project_to_patches_map[p.project].append(p)

    if dropped_changes:
      presentation.logs['changes not applied'] = dropped_changes
      presentation.step_text = 'some changes not applied as they are not supported by this builder.'

    return project_to_patches_map


def apply_changes_and_run_presubmits(api, project, patch_sets):
  """For a given project, clone the repo, apply changes and run presubmits.

  Args:
    api (RecipeApi): See RunSteps documentation.
    project (str): The name of the Gerrit project.
    patch_sets (list[PatchSet]): List of changes to apply for the given project.
  """
  with api.step.nest('apply changes and run presubmits for %s' % project):
    project_path = _clone_repo(api, patch_sets[0].host, patch_sets[0].project)
    for patch in patch_sets:
      api.cros_source.apply_patch_set(patch, project_path, is_abs_path=True)
    _run_presubmits(api, project_path)


def _clone_repo(api, host, project):
  """Create a Git clone in a temporary directory.

  Args:
    api: The recipe modules API.
    host: The Gerrit host the project belongs to.
    project: The name of the Gerrit project.

  Returns:
    The path to the newly cloned Git checkout.
  """
  if host == INTERNAL_REVIEW_HOST:
    repo_url = INTERNAL_HOST_REPO_TEMPLATE % project
  elif host == EXTERNAL_REVIEW_HOST:
    repo_url = EXTERNAL_HOST_REPO_TEMPLATE % project
  else:
    raise StepFailure('Could not determine repo location for the project')

  repo_dir = api.path.mkdtemp()
  api.git.clone(repo_url, repo_dir)

  return repo_dir


def _run_presubmits(api, full_path):
  """Run the presubmits defined in PRESUBMIT.py.

  Args:
    api (RecipeApi): See RunSteps documentation.
    full_path (str): The path to the Git checkout.
  """
  with api.step.nest('run presubmit checks') as presentation:
    with api.context(cwd=full_path), api.depot_tools.on_path():

      # Several checks require that we have an upstream tracking branch.
      # This requires us to have a branch, which we don't yet have.
      # Create the "__presubmit" branch, run the check, and then delete it.
      with api.git.head_context():
        api.step('setup', ['git', 'checkout', '-b', '__presubmit'])
        api.step('set tracking',
                 ['git', 'branch', '--set-upstream-to', 'origin/main'])

        test_presubmit_file = api.properties.get('test_presubmit_file',
                                                 'PRESUBMIT.py')
        api.path.mock_add_paths(full_path.join(test_presubmit_file))

        # To start, this Recipe will only support running the PRESUBMIT.py file.
        if api.path.exists(full_path.join('PRESUBMIT.py')):
          api.step('git cl presubmit', ['git', 'cl', 'presubmit', '--verbose'])
        else:
          presentation.step_text = 'No PRESUBMIT file found.'

      # The branch isn't merged, so we have to use -D.
      api.step('branch cleanup', ['git', 'branch', '-D', '__presubmit'])


def GenTests(api):
  gerrit_changes = [
      common_pb2.GerritChange(host='chromium-review.googlesource.com',
                              project='p1', change=1234),
      common_pb2.GerritChange(host='chrome-internal-review.googlesource.com',
                              project='p2', change=1235),
      common_pb2.GerritChange(host='chrome-internal-review.googlesource.com',
                              project='p2', change=2341),
  ]

  yield api.test('no-changes', api.buildbucket.try_build(gerrit_changes=[]))

  yield api.test('no-eligible-changes',
                 api.buildbucket.try_build(gerrit_changes=gerrit_changes))

  yield api.test('some-elegible-changes',
                 api.buildbucket.try_build(gerrit_changes=gerrit_changes),
                 api.properties(project_names=['p1']))

  yield api.test('all-elegible-changes',
                 api.buildbucket.try_build(gerrit_changes=gerrit_changes),
                 api.properties(project_names=['p1', 'p2']))

  yield api.test('no-presubmit-file',
                 api.buildbucket.try_build(gerrit_changes=gerrit_changes),
                 api.properties(test_presubmit_file=''),
                 api.properties(project_names=['p1', 'p2']))

  gerrit_change = common_pb2.GerritChange(host='unknow-review.googlesource.com',
                                          project='p1', change=1234)
  yield api.test(
      'cannot-resolve-repo-url',
      api.buildbucket.try_build(gerrit_changes=[gerrit_change]),
      api.properties(test_presubmit_file=''),
      api.properties(project_names=['p1', 'p2']),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
