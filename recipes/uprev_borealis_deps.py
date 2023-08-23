# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for upreving Borealis build dependencies."""
from typing import Optional

from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

from PB.recipes.chromeos.uprev_borealis_deps import (UprevBorealisDepsProperties
                                                    )
from recipe_engine import post_process
from recipe_engine.engine_types import StepPresentation
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'build_menu',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = UprevBorealisDepsProperties
GERRIT_CL_TOPIC = 'borealis-deps'
GERRIT_CL_REVIEWERS = ['davidriley@google.com', 'pobega@google.com']

_BOREALIS_REPO_PATH = 'src/platform/borealis/'


def RunSteps(api: RecipeApi, properties: UprevBorealisDepsProperties):
  with api.build_menu.configure_builder(missing_ok=True), \
    api.build_menu.setup_workspace(), api.cros_sdk.cleanup_context():
    api.cros_sdk.create_chroot(version=None, timeout_sec=None)
    api.cros_sdk.update_chroot(timeout_sec=None)

    return DoRunSteps(api, properties)


def DoBorealisBuild(api: RecipeApi, use_cache: bool = True,
                    skip_termina: bool = False, stage: Optional[str] = None):
  """Perform a Borealis build_full.

  Args:
    api: The recipe modules API.
    use_cache: Use cached step results from previous builds.
    skip_termina: Use a prebuilt copy of termina-tools
    stage: The name of the step from the Dockerfile to build. Does not
      perform a full build, will stop after the specified stage is built.
  """
  # --skip-license-report is needed for early stage builds to work without
  # error since they don't run `build/usr/bin/stamp-lsb-release.sh`
  build_command = ['./tools/build_full.py', '--skip-license-report']
  if stage:
    build_command.append('--stage')
    build_command.append(stage)
    # When building a stage directly there's no guarantee the tests will
    # exist, so skip running tests if a stage is specified.
    build_command.append('--no-run-tests')
  if not use_cache:
    build_command.append('--no-cache')
  if skip_termina:
    build_command.append('--skip-termina')
  api.step('Borealis build_full.py', build_command)


def _CommitChanges(api: RecipeApi, project: ProjectInfo, commit_message: str,
                   branch_name: str = None):
  """Commit changes to the Borealis build/ and tools/arch_verity/ directories.

  Args:
    api: The recipe modules API.
    project: Project object obtained from api.repo.project_info
    commit_message: Git commit message to use.
    branch_name: Name for the local branch for repo start
  """
  borealis_repo_path = api.cros_source.workspace_path.join(_BOREALIS_REPO_PATH)
  with api.step.nest('commit changes'), \
          api.context(cwd=borealis_repo_path):
    # Add a branch to avoid re-using the old commit and creating a
    # patchseries (we want unique and separate CLs)
    repo_branch = 'uprev-borealis-deps'
    if branch_name:
      # Remove all non-alphabetical characters to ensure valid branch name
      repo_branch = ''.join([char for char in branch_name if char.isalpha()])
    api.repo.start(repo_branch, projects=[project.name])

    # Commit all changes in platform/borealis/{build,tools/arch_verity}/
    api.git.add(['build/'])
    api.git.add(['tools/arch_verity/'])
    api.git.commit(commit_message)


def _CreateCL(api: RecipeApi, project: ProjectInfo,
              presentation: StepPresentation):
  """Upload Git changes as a Gerrit CL.

  Args:
    api: The recipe modules API.
    project: Project object obtained from api.repo.project_info
    presentation: the step to write the CL link to (for LUCI web UI)
  """
  with api.step.nest('upload CL to gerrit') as nested_presentation:
    change = api.gerrit.create_change(project=project.name,
                                      topic=GERRIT_CL_TOPIC,
                                      reviewers=GERRIT_CL_REVIEWERS)
    labels = {
        Label.BOT_COMMIT: 1,
        Label.COMMIT_QUEUE: 2,
    }
    api.gerrit.set_change_labels(change, labels)
    if presentation:
      presentation.links['Gerrit CL'] = api.gerrit.parse_gerrit_change_url(
          change)
    nested_presentation.links['Gerrit CL'] = api.gerrit.parse_gerrit_change_url(
        change)


def CommitChangesAndCreateCL(api: RecipeApi, step_name: str,
                             commit_message: str,
                             presentation: StepPresentation):
  """Create Git commit from changes and upload Gerrit CL.

  Args:
    api: The recipe modules API.
    step_name: Name of the step to nest operations from.
    commit_message: Git commit message to use.
    presentation: the API step to show the Gerrit CL URL
  """
  project = api.repo.project_info(project=api.git.repository_root())

  with api.step.nest(step_name):
    # Only commit and create CL on non-staging jobs.
    # Committing an empty change results in an INFRA_FAILURE which can be
    # easily caused as a race condition if the staging job is scheduled to run
    # shortly after the prod job.
    if not api.build_menu.is_staging:
      _CommitChanges(api, project, commit_message, step_name)
      _CreateCL(api, project, presentation)


def DoRunSteps(api: RecipeApi, properties: UprevBorealisDepsProperties):
  chroot_path = api.cros_source.workspace_path
  borealis_path = chroot_path.join(_BOREALIS_REPO_PATH)
  with api.depot_tools.on_path(), api.context(cwd=borealis_path):
    # This recipe should only run on bots with docker pre-installed.  Abort
    # immediately if that is not the case.
    api.step('check docker install', ['docker', 'help'])

    # Do an initial stage build to generate termina-tools
    DoBorealisBuild(api, use_cache=False, skip_termina=False, stage='initial')

    # Uprev Arch historic mirror
    if properties.uprev_arch_mirror:
      with api.step.nest('Arch mirror uprev') as presentation:
        api.step('Arch mirror uprev', ['./tools/arch_mirror_uprev.py'])
        # Test that build_full still builds
        DoBorealisBuild(api, skip_termina=True)
        # Create Arch mirror uprev CL
        commit_message = 'uprev Arch historic mirror\n\n'
        commit_message += 'CL generated by job {}'.format(
            api.buildbucket.build_url())
        api.step('Arch db checksum update',
                 ['./tools/arch_verity/checksum_tool.py', '--update'])
        api.step('Verify new Arch db checksums',
                 ['./tools/arch_verity/checksum_tool.py', '--verify'])
        CommitChangesAndCreateCL(api, 'create Arch mirror CL', commit_message,
                                 presentation)

    # Uprev PKGBUILDs
    if properties.uprev_pkgbuilds:
      with api.step.nest('PKGBUILDs uprev') as presentation:
        api.step('PKGBUILD uprev', ['./tools/pkgbuild_uprev.py', '--all'])
        # Test that build_full still builds
        DoBorealisBuild(api, skip_termina=True)
        # Create PKGBUILD uprev CL
        commit_message = 'uprev PKGBUILDs\n\n'
        commit_message += 'CL generated by job {}'.format(
            api.buildbucket.build_url())
        # TODO: on the second run this creates a patchseries CL so the URL
        # provided is the same as the first.
        CommitChangesAndCreateCL(api, 'create PKGBUILDs CL', commit_message,
                                 presentation)


def GenTests(api: RecipeTestApi):
  good_props = {'uprev_arch_mirror': True, 'uprev_pkgbuilds': True}
  yield api.test(
      'basic',
      api.properties(**good_props),
  )

  yield api.test(
      'borealis build_full.py args', api.properties(**good_props),
      api.post_process(
          post_process.StepCommandContains,
          'Borealis build_full.py',
          [
              '--skip-license-report',
              '--stage',
              'initial',
              '--no-run-tests',
              '--no-cache',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'Arch mirror uprev.Borealis build_full.py',
          [
              '--skip-license-report',
              '--skip-termina',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'PKGBUILDs uprev.Borealis build_full.py',
          [
              '--skip-license-report',
              '--skip-termina',
          ],
      ), api.post_process(post_process.DropExpectation))

  props = good_props.copy()
  del props['uprev_arch_mirror']
  yield api.test('no uprev arch', api.properties(**props),
                 api.post_check(post_process.MustRun, 'Borealis build_full.py'),
                 api.post_check(post_process.DoesNotRun, 'Arch mirror uprev'),
                 api.post_check(post_process.MustRun, 'PKGBUILDs uprev'),
                 api.post_process(post_process.DropExpectation))

  props = good_props.copy()
  del props['uprev_pkgbuilds']
  yield api.test('no uprev pkgbuilds', api.properties(**props),
                 api.post_check(post_process.MustRun, 'Borealis build_full.py'),
                 api.post_check(post_process.MustRun, 'Arch mirror uprev'),
                 api.post_check(post_process.DoesNotRun, 'PKGBUILDs uprev'),
                 api.post_process(post_process.DropExpectation))

  props = good_props.copy()
  del props['uprev_arch_mirror']
  del props['uprev_pkgbuilds']
  yield api.test('no uprevs', api.properties(**props),
                 api.post_check(post_process.MustRun, 'Borealis build_full.py'),
                 api.post_check(post_process.DoesNotRun, 'Arch mirror uprev'),
                 api.post_check(post_process.DoesNotRun, 'PKGBUILDs uprev'),
                 api.post_process(post_process.DropExpectation))
