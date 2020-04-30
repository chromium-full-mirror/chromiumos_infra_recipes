# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running presubmit on multiple CLs."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'gitiles',
    'repo',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.presubmit_tests import PresubmitTestsProperties

PROPERTIES = PresubmitTestsProperties


def RunSteps(api, properties):
  gitiles_commit = api.buildbucket.gitiles_commit
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  # There are 3 use cases here:
  # 1. No gerrit changes: pointless.
  # 2. No gitiles_commit, with gerrit_changes:
  #    This build was launched by luci-cq (or a user).
  #    Use refs/heads/snapshot and the buildbucket-specified gerrit_changes.
  # 3. Gitiles_commit, with gerrit_changes:
  #    This build was launched by a user.
  #    Use the given information.

  # TODO(crbug/1039875): Look at moving this code to a recipe module and using
  # that both here, and in orchestrator.determine_repo_state.
  with api.step.nest('validate inputs') as presentation:
    # If there are no gerrit_changes, we're done.
    if not len(gerrit_changes):
      presentation.step_text = "No changes given:  Build is POINTLESS."
      return

    # If we did not get a gitiles_commit, use refs/heads/snapshot.
    if not gitiles_commit.project:
      with api.step.nest('fetch snapshot ref'):
        gitiles_commit = common_pb2.GitilesCommit(
            host='chrome-internal.googlesource.com',
            project='chromeos/manifest-internal', ref='refs/heads/snapshot')
      # The gitiles_commit we have may not have an id, which will be needed
      # later.  If we need to, re-create the gitiles_commit with the right id.
      if not gitiles_commit.id:
        gitiles_commit = common_pb2.GitilesCommit(
            host=gitiles_commit.host, project=gitiles_commit.project,
            ref=gitiles_commit.ref,
            id=api.gitiles.fetch_revision(gitiles_commit.host,
                                          gitiles_commit.project,
                                          gitiles_commit.ref))

  # TODO(crbug/1039875): Add an input property to only do the minimal checkouts
  # required.
  _FullCheckout(api, properties, gitiles_commit, gerrit_changes)


def _FullCheckout(api, properties, gitiles_commit, gerrit_changes):
  # Some of the repos (e.g., crostools) reach into other repos in presubmit
  # checks.  As such, we grab sync the source tree.  Start with a full checkout
  # of the manifest, apply the changes, and then run presubmit checks.
  workpath = api.cros_source.workspace_path
  with api.cros_source.checkout_overlays_context(), api.context(cwd=workpath), \
      api.cros_sdk.cleanup_context(checkout_path=workpath):
    api.cros_source.ensure_synced_cache()
    api.cros_source.sync_snapshot(gitiles_commit)

    with api.step.nest('cherry-pick gerrit changes'):
      patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
      new_commits = api.cros_source.apply_gerrit_patch_sets(patch_sets)

    with api.step.nest('run presubmit checks'):
      # Set up some variables that are used repeatedly in the for loop.
      path_info = {
          x.path: x for x in api.repo.project_infos(
              projects=[x.project for x in patch_sets])
      }
      dry_run = api.cq.state == api.cq.DRY

      checked_paths = set()

      for patch, commit in zip(patch_sets, new_commits):
        if commit.path in checked_paths:
          continue
        checked_paths.add(commit.path)
        full_path = workpath.join(commit.path)
        with api.step.nest('checking %s' % commit.path) as presentation:

          info = path_info[commit.path]
          branch = api.git.extract_branch(info.branch, 'master')
          with api.context(cwd=full_path), api.depot_tools.on_path():
            # Several checks require that we have an upstream tracking branch.
            # This requires us to have a branch, which we don't yet have.
            # Create the "__presubmit" branch, run the check, and then delete
            # it.
            with api.git.head_context():
              api.step('setup', ['git', 'checkout', '-b', '__presubmit'])
              api.step('set tracking', [
                  'git', 'branch', '--set-upstream-to',
                  '%s/%s' % (info.remote, branch)
              ])
              api.path.mock_add_paths(full_path.join(properties.test_filename))
              if api.path.exists(full_path.join('PRESUBMIT.cfg')):
                api.step('repo presubmit', [
                    workpath.join('src/repohooks/pre-upload.py'), '--pre-submit'
                ])
              elif api.path.exists(full_path.join('PRESUBMIT.py')):
                api.step('git cl presubmit',
                         ['git', 'cl', 'presubmit', '--verbose'])
              else:
                presentation.step_text = 'No PRESUBMIT file found.'
            # The branch isn't merged, so we have to use -D.
            api.step('branch cleanup', ['git', 'branch', '-D', '__presubmit'])


def GenTests(api):
  mock_CLs = [
      common_pb2.GerritChange(host='chromium.googlesource.com', project='p1',
                              change=1234),
      common_pb2.GerritChange(host='chrome-internal.googlesource.com',
                              project='p2', change=2341),
  ]

  def test_builder(builder='infra-presubmit', gitiles=True, changes=True):
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder=builder)
    if not gitiles:
      build.input.gitiles_commit.Clear()
    if changes:
      build.input.gerrit_changes.extend(mock_CLs)
    return api.buildbucket.build(build)

  yield api.test('basic', test_builder())

  yield api.test('missing', test_builder(builder='missing'))

  yield api.test('no gitiles given', test_builder(gitiles=False))

  yield api.test('no changes given', test_builder(gitiles=False, changes=False))

  yield api.test(
      'no config gitiles',
      test_builder(builder='amd64-generic-cq', gitiles=False, changes=False))

  yield api.test('has PRESUBMIT.py', test_builder(), api.cq(dry_run=True),
                 api.properties(test_filename='PRESUBMIT.py'))

  yield api.test('has PRESUBMIT.cfg', test_builder(),
                 api.properties(test_filename='PRESUBMIT.cfg'))
