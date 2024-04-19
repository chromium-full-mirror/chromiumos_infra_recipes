# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Compile and sync proto files across ChromeOS.

This recipe should normally be triggered via a gitiles_poller that watches for
changes to the infra/proto repo. The poller should batch requests, so there may
be several changes, which may be on different branches.
For more info on gitiles_pollers, see go/lucicfg#luci.gitiles_poller.
"""

from typing import Generator, List, Optional

from PB.chromite.api import api as api_service
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)
from PB.recipes.chromeos import proto_doctor as proto_doctor_pb2
from recipe_engine import config_types
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from RECIPE_MODULES.chromeos.gerrit import api as gerrit_api
from RECIPE_MODULES.chromeos.repo import api as repo_api

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_build_api',
    'cros_sdk',
    'deferrals',
    'easy',
    'gerrit',
    'git',
    'repo',
    'src_state',
    'workspace_util',
]

PROPERTIES = proto_doctor_pb2.ProtoDoctorProperties

# Repo projects.
CHROMITE_REPO = 'chromiumos/chromite'
INFRA_PROTO_REPO = 'chromiumos/infra/proto'
CHROMITE_INFRA_PROTO_REPO = 'chromite/infra/proto'
CHROMIUMOS_OVERLAY_REPO = 'src/third_party/chromiumos-overlay'
MANIFEST_INTERNAL_REPO = 'chromeos/manifest-internal'
SCRIPTS_REPO = 'src/scripts'
PROJECTS_TO_CHECKOUT = (
    INFRA_PROTO_REPO,
    CHROMITE_REPO,
    CHROMITE_INFRA_PROTO_REPO,
    CHROMIUMOS_OVERLAY_REPO,  # Needed for SDK version file.
    MANIFEST_INTERNAL_REPO,  # Needed to check the ChromeOS version
    SCRIPTS_REPO,  # Needed for make_chroot.sh script.
)

# URLs for repo projects. This is what appears in a gitiles trigger.
INFRA_PROTO_REPO_URL = f'https://chromium.googlesource.com/{INFRA_PROTO_REPO}'
CHROMITE_REPO_URL = f'https://chromium.googlesource.com/{CHROMITE_REPO}'

# Branches and refs.
MAIN_BRANCH = 'main'
MAIN_REF = 'refs/heads/main'

# Timing constants, in case not specified via input properties.
DEFAULT_OPEN_CL_POLL_INTERVAL_SECS = 2 * 60  # 2 minutes.
DEFAULT_OPEN_CL_POLL_TIMEOUT_SECS = 60 * 60  # 1 hour.

# Hashtag used to identify CLs launched by ProtoDoctor.
# Note that the hashtag alone is not sufficient to identify ProtoDoctor CLs,
# since a human user could also use the same hashtag.
# But checking hashtag + owner should be sufficient.
HASHTAG = 'protodoctor'

# COMMIT_TEMPLATE is a template for commit messages created by ProtoDoctor.
# {subject} is a short (<=50 characters) description of the CL.
# {url} is the buildbucket URL of the ProtoDoctor build that created the CL,
# usually fetched via api.buildbucket.build_url().
# {infra_proto_hash} is the commit hash in infra/proto that was used to generate
# the change.
COMMIT_TEMPLATE = '''{subject}

This CL was automatically created by ProtoDoctor.
{url}

Proto-Commit: {infra_proto_hash}

BUG=None
TEST=CQ'''


def RunSteps(api: recipe_api.RecipeApi,
             properties: proto_doctor_pb2.ProtoDoctorProperties) -> None:
  """Starting point for main recipe logic.

  This function does setup, determines which branches to work on, and then
  defers to child functions for specific processing.
  """
  ProtoDoctorRun(api, properties).run()


class ProtoDoctorRun:
  """A single run of ProtoDoctor."""

  def __init__(self, api: recipe_api.RecipeApi,
               properties: proto_doctor_pb2.ProtoDoctorProperties) -> None:
    """Initialize up the class by setting basic attributes."""
    self.m = api
    self.properties = properties

    # The ref currently being worked on.
    # By setting this as an attribute, we avoid needing to pass it as a param
    # into most functions. Normally it should be accessed by the @properties
    # self.current_ref and self.current_branch, which will fail gracefully
    # if self._current_ref is None.
    self._current_ref: Optional[str] = None

  @property
  def _is_staging(self) -> bool:
    """Determine whether this is a staging build."""
    return self.m.buildbucket.build.builder.bucket == 'staging'

  @property
  def _gitiles_triggers(self) -> List[triggers_pb2.GitilesTrigger]:
    """Return a list of GitilesTriggers that launched this build."""
    gitiles_triggers: List[triggers_pb2.GitilesTrigger] = []
    for trigger in self.m.scheduler.triggers:
      if not trigger.HasField('gitiles'):
        continue
      gitiles_triggers.append(trigger.gitiles)
    return gitiles_triggers

  @property
  def _workspace_path(self) -> config_types.Path:
    """Return the build's workspace path, where `repo` should be checked out."""
    return self.m.src_state.workspace_path

  @property
  def current_ref(self) -> str:
    """Return the ref currently being worked on.

    Raises:
      AssertionError: If no branch is currently being worked on.
    """
    assert self._current_ref is not None
    return self._current_ref

  @property
  def current_branch(self) -> str:
    """Return the branch currently being worked on.

    Raises:
      AssertionError: If no branch is currently being worked on.
    """
    return self.m.git.extract_branch(self.current_ref)

  def run(self) -> None:
    """Run the main recipe logic.

    This function does setup,d etermines which branches to work on, and then
    defers to child methods for specific processing.
    """
    self._validate_triggers()
    refs = sorted(set(gt.ref for gt in self._gitiles_triggers))
    self.m.easy.set_properties_step(refs=refs)
    self._create_workspace_dir()

    # If one branch raises an exception, defer the exception so that the other
    # branches can run.
    with self.m.deferrals.raise_exceptions_at_end():
      for ref in refs:
        with self.m.deferrals.defer_exceptions():
          self._process_ref(ref)

  def _validate_triggers(self) -> None:
    """Verify that the build's triggers look OK.

    In general, this recipe should be triggered by Gitiles changes to the
    infra/proto repo.

    See https://go.chromium.org/luci/scheduler/api/scheduler/v1 for more info
    about triggers and the different trigger types.

    Raises:
      InfraFailure: If the build does not have any Gitiles triggers.
      InfraFailure: If any of the build's triggering CLs was from a repo besides
        infra/proto.
    """
    with self.m.step.nest('validate triggers'):
      for gt in self._gitiles_triggers:
        if gt.repo != INFRA_PROTO_REPO_URL:
          raise recipe_api.InfraFailure(
              f'Gitiles trigger in non-proto repo: {gt}')
      if not self._gitiles_triggers:
        raise recipe_api.InfraFailure('No Gitiles triggers found')

  def _create_workspace_dir(self) -> None:
    """Create the workspace path directory."""
    self.m.step('setup workspace dir', ['mkdir', self._workspace_path])

  def _process_ref(self, ref: str) -> None:
    """For a single manifest branch, propagate proto changes across the tree.

    Args:
      ref: The git ref for the branch to work from, such as "refs/heads/main".
    """
    self._current_ref = ref
    with self.m.step.nest(f'process branch {self.current_branch}'):
      self._setup_branch()
      self._wait_for_open_cls()
      self._abandon_stale_cls()
      self._compile_chromite_protos()
    self._current_ref = None

  def _setup_branch(self) -> None:
    """Check out necessary projects and create an SDK on the current branch."""
    with self.m.context(cwd=self._workspace_path):
      self.m.repo.init(
          manifest_url=self.m.src_state.internal_manifest.url,
          manifest_branch=self.current_branch,
      )
      self.m.repo.sync(projects=list(PROJECTS_TO_CHECKOUT))
      self.m.cros_sdk.create_chroot()

  def _wait_for_open_cls(self) -> None:
    """Block until all open ProtoDoctor CLs on the branch are done with CQ.

    Raises:
      StepFailure: If too much time passed while waiting for CLs to finish.
    """
    start_time = self.m.time.time()  # Measured in seconds.

    def elapsed_seconds() -> float:
      """Return the number of seconds elapsed since polling started."""
      return self.m.time.time() - start_time

    interval_secs = (
        self.properties.open_cl_poll_interval_secs or
        DEFAULT_OPEN_CL_POLL_INTERVAL_SECS)
    timeout_secs = (
        self.properties.open_cl_poll_timeout_secs or
        DEFAULT_OPEN_CL_POLL_TIMEOUT_SECS)

    with self.m.step.nest('wait for open cls'):
      while elapsed_seconds() < timeout_secs:
        if self._get_open_proto_doctor_cls(only_with_active_cq=True):
          # Some CLs are still running CQ. Keep polling.
          self.m.time.sleep(interval_secs)
        else:
          # No CLs are running CQ anymore. Stop blocking.
          return
      # Timed out while polling.
      raise recipe_api.StepFailure('Timed out waiting for CQ to finish.')

  def _abandon_stale_cls(self) -> None:
    """If there are any stale ProtoDoctor CLs on Gerrit, abandon them.

    Generally, this method should be called after self._wait_for_open_cls().
    Thus, any CLs abandoned here should not still be running CQ.

    This method only affects CLs on the current branch.
    """
    with self.m.step.nest('abandon old cls'):
      stale_cls = self._get_open_proto_doctor_cls()
      message = (
          'This CL is stale. It will be replaced by a newer CL. See the '
          f'following ProtoDoctor build: {self.m.buildbucket.build_url()}')
      for cl in stale_cls:
        self.m.gerrit.abandon_change(cl, message=message)

  def _get_open_proto_doctor_cls(
      self,
      only_with_active_cq: bool = False) -> List[bb_common_pb2.GerritChange]:
    """Return a list of open ProtoDoctor CLs on the current branch.

    Args:
      only_with_active_cq: If True, only return a list of CLs that are currently
        active in CQ, whether CQ+1 or CQ+2.
    """
    if not self.properties.expected_cl_owners:
      raise recipe_api.InfraFailure(
          'Cannot find old ProtoDoctor CLs, because expected CL owners were not '
          'specified.')
    label_constraints: Optional[List[gerrit_api.LabelConstraint]] = None
    if only_with_active_cq:
      label_constraints = [
          gerrit_api.LabelConstraint(
              label=gerrit_api.Label.COMMIT_QUEUE,
              kind=gerrit_api.LabelConstraintKind.ANY_NONZERO_VOTE)
      ]
    open_changes: List[bb_common_pb2.GerritChange] = []
    for host in (gerrit_api.EXTERNAL_HOST, gerrit_api.INTERNAL_HOST):
      for cl_owner in self.properties.expected_cl_owners:
        query_params = [
            ('owner', cl_owner),
            ('hashtag', HASHTAG),
            ('branch', self.current_branch),
        ]
        open_changes.extend(
            self.m.gerrit.query_changes(host=host, query_params=query_params,
                                        label_constraints=label_constraints))
    return open_changes

  def _compile_chromite_protos(self) -> None:
    """Compile proto bindings in chromite/, and upload to Gerrit."""
    with self.m.step.nest('compile chromite protos'):
      request = api_service.CompileProtoRequest()
      response = self.m.cros_build_api.ApiService.CompileProto(request)
      modified_paths = [f.path for f in response.modified_files]
      chromite_path = self._workspace_path.join('chromite')
      with self.m.context(cwd=chromite_path):
        chromite = self.m.repo.project_info(
            # Use the absolute path to disambiguate from chromite-HEAD.
            chromite_path,
            test_data='chromiumos/chromite|chromite|cros|refs/heads/main|')
      commit_subject = 'api: Automatically compile protos'
      self._commit_and_upload(chromite, modified_paths, commit_subject)

  def _commit_and_upload(self, project: repo_api.ProjectInfo,
                         modified_paths: List[config_types.Path],
                         commit_subject: str) -> None:
    """Commit all code in the modified project, and upload it to Gerrit."""
    self._create_commit(project, modified_paths, commit_subject)
    if not self._is_staging:
      self._push_to_cq(project)

  def _create_commit(self, project: repo_api.ProjectInfo,
                     modified_paths: List[config_types.Path],
                     subject: str) -> None:
    """Create a new (temporary) branch and commit the modified files.

    Note: Although this creates a branch, it does not reset self._current_ref,
    since it doesn't change which manifest branch is being worked from. The
    caller should typically check back out the current_branch afterward.

    Args:
      project: The repo project in which to commit.
      modified_paths: A list of modified files to commit within the project.
      subject: The first line to write in the new commit.
    """
    with self.m.context(cwd=self._workspace_path.join(project.path)):
      self.m.repo.start('proto-doctor', [project.path])
      self.m.git.add(modified_paths)
      message = self._create_commit_message(subject)
      self.m.git.commit(message)

  def _create_commit_message(self, subject: str) -> str:
    """Create and return a commit message for a new ProtoDoctor CL.

    Args:
      subject: The first line to write in the new commit.
    """
    url = self.m.buildbucket.build_url()
    with self.m.context(cwd=self._workspace_path.join('infra', 'proto')):
      infra_proto_hash = self.m.easy.stdout_step(
          'get infra/proto commit hash',
          ['git', 'rev-parse', 'HEAD'],
          test_stdout=b'deadb33f',
          infra_step=True,
      ).decode().strip()
    return COMMIT_TEMPLATE.format(subject=subject, url=url,
                                  infra_proto_hash=infra_proto_hash)

  def _push_to_cq(self, project: repo_api.ProjectInfo) -> None:
    """Upload the local changes for the given project, and send to CQ.

    TODO(b/282971123): Once we've confirmed that the generated CLs look OK, use
    CQ+2.

    Args:
      project: The repo project containing a local commit to push.
    """
    assert not self._is_staging
    ccs = self._get_ccs_for_project(project)
    change = self.m.gerrit.create_change(
        # Use the absolute project path to avoid any ambiguity.
        project=self._workspace_path.join(project.path),
        ccs=ccs,
        ref=self.current_ref,
        hashtags=[HASHTAG])
    labels = {gerrit_api.Label.COMMIT_QUEUE: 1}
    self.m.gerrit.set_change_labels_remote(change, labels)

  def _get_ccs_for_project(self, project: repo_api.ProjectInfo) -> List[str]:
    """Return a list of Gerrit users to cc on a ProtoDoctor CL in the project.

    This will be a list of users who have submitted .proto changes to the
    infra/proto project on the checked-out branch more recently than the
    infra/proto CL to which `project` was most recently updated on the branch.

    If no ProtoDoctor CL has ever been merged onto the project+branch, just cc
    the user who wrote the most recent infra/proto CL on the given branch.
    """
    # from_hash is the git commit hash in the infra/proto repo from which the
    # most recent ProtoDoctor CL was generated.
    # If no ProtoDoctor CL has ever been submitted on this project+branch, use
    # HEAD~, so that we'll only see the most recent infra/proto commit.
    # (Remember that HEAD~ is the commit immediately before HEAD.)
    from_hash = self._get_most_recent_proto_hash(project) or 'HEAD~'

    authors: bytes = self.m.easy.stdout_step(
        'get infra/proto authors to cc',
        [
            'git',
            'log',
            '--pretty=format:"%aE"',  # Just print the email addresses.
            f'{from_hash}..',  # All commits later than from_hash.
            '**.proto',  # Only cc authors who modified .proto files.
        ],
        test_stdout=b'larry@google.com\nsergey@google.com')
    authors: List[str] = authors.decode().strip().split('\n')
    # Deduplicate, and ensure a deterministic order for testing.
    return sorted(set(authors))

  def _get_most_recent_proto_hash(
      self, project: repo_api.ProjectInfo) -> Optional[str]:
    """Get the proto hash from the latest ProtoDoctor CL on this project+branch.

    This method queries Gerrit to find the most recent ProtoDoctor CL, and then
    parses the commit message to find which infra/proto commit it used. There
    should be a line like:
      Proto-Commit: deadb33f

    Returns:
      The extracted commit hash of the latest ProtoDoctor CL in the given
      project in the current branch. If no ProtoDoctor CL can be found, or if
      the most recent CL's commit message does not contain the expected line,
      then None.
    """
    # TODO(b:282975918): Implement this.
    # Until then, always return None. This will cause _get_ccs_for_project() to
    # return the most recent infra/proto committer, which is good enough to
    # ship.
    del project


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Generate test cases for this recipe."""
  release_branch = 'release-R100-14526.B'
  release_ref = f'refs/heads/{release_branch}'

  # Triggers used for testing.
  gitiles_trigger_main = triggers_pb2.GitilesTrigger(repo=INFRA_PROTO_REPO_URL,
                                                     ref=MAIN_REF,
                                                     revision='aaaaaa')
  gitiles_trigger_main2 = triggers_pb2.GitilesTrigger(
      repo=INFRA_PROTO_REPO_URL,
      ref=MAIN_REF,
      revision='bbbbbb',
  )
  gitiles_trigger_release_branch = triggers_pb2.GitilesTrigger(
      repo=INFRA_PROTO_REPO_URL, ref=release_ref, revision='cccccc')
  gitiles_trigger_chromite = triggers_pb2.GitilesTrigger(
      repo=CHROMITE_REPO_URL,
      ref=MAIN_REF,
      revision='dddddd',
  )
  buildbucket_trigger = triggers_pb2.BuildbucketTrigger(tags=['a:b'])

  # Gerrit changes used for testing.
  cq_active_cl = {
      '_number': 12345,
      'project': CHROMITE_REPO,
      'labels': {
          'Commit-Queue': {
              'all': [{
                  'value': 1,
              },],
          }
      }
  }
  cq_inactive_cl = {
      '_number': 12345,
      'project': CHROMITE_REPO,
      'labels': {
          'Commit-Queue': {}
      }
  }

  yield api.test(
      'basic',
      api.properties(expected_cl_owners=['sundar@google.com']),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_release_branch),
          # Buildbucket trigger should be ignored.
          triggers_pb2.Trigger(buildbucket=buildbucket_trigger),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main2),
      ]),
      # Each branch should only be processed once, despite multiple triggers.
      api.post_check(post_process.MustRun, f'process branch {MAIN_BRANCH}'),
      api.post_check(post_process.DoesNotRun,
                     f'process branch {MAIN_BRANCH} (2)'),
      api.post_check(post_process.MustRun, f'process branch {release_branch}'),

      ### Waiting for open CLs to finish CQ ###
      # On the main branch on the external host, for the first query, find a
      # CQ-active change so that we need to re-poll.
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [cq_active_cl],
          gerrit_api.EXTERNAL_HOST),
      # For the second query, let that change be done with CQ.
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [cq_inactive_cl],
          gerrit_api.EXTERNAL_HOST, iteration=2),
      # Assert that there is no third query.
      # (Assert we _do_ run iteration #2 to ensure we have the step name right.)
      api.post_check(
          post_process.MustRun,
          f'process branch main.wait for open cls.query {gerrit_api.EXTERNAL_HOST} (2)'
      ),
      api.post_check(
          post_process.DoesNotRun,
          f'process branch main.wait for open cls.query {gerrit_api.EXTERNAL_HOST} (3)'
      ),
      # For simplicity, no open CLs on other branches or on the internal host.
      # (Internal host needs a second iteration because it requeries alongside
      # the external host.)
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [],
          gerrit_api.INTERNAL_HOST),
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [], gerrit_api.INTERNAL_HOST,
          iteration=2),
      api.gerrit.set_query_changes_response(
          f'process branch {release_branch}.wait for open cls', [],
          gerrit_api.EXTERNAL_HOST),
      api.gerrit.set_query_changes_response(
          f'process branch {release_branch}.wait for open cls', [],
          gerrit_api.INTERNAL_HOST),

      # Check that the expected Chromite files get uploaded
      api.post_check(
          post_process.StepCommandContains,
          'process branch main.compile chromite protos.git add', [
              '[CLEANUP]/chromiumos_workspace/chromite/api/gen/some_file_pb2.py',
              '[CLEANUP]/chromiumos_workspace/chromite/api/gen_sdk/some_file_pb2.py',
          ]),
      # Production builder should actually upload changes
      api.post_check(
          post_process.MustRun,
          '.'.join((
              'process branch main', 'compile chromite protos',
              'create gerrit change for [CLEANUP]/chromiumos_workspace/chromite'
          )),
      ),
      api.post_check(
          post_process.LogEquals,
          'process branch main.compile chromite protos.set labels on CL 1',
          'labels',
          '{"Commit-Queue": 1}',
      ),
  )

  yield api.test(
      'staging',
      api.properties(expected_cl_owners=['sundar@google.com']),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
      ]),
      # For simplicity, no open CLs to wait for.
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [],
          gerrit_api.EXTERNAL_HOST),
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [],
          gerrit_api.INTERNAL_HOST),
      # Staging branch should make local changes, but not upload.
      api.post_check(
          post_process.MustRun,
          '.'.join((
              'process branch main',
              'compile chromite protos',
              'call chromite.api.ApiService/CompileProto',
          )),
      ),
      api.post_check(
          post_process.MustRun,
          'process branch main.compile chromite protos.git commit',
      ),
      api.post_check(
          post_process.DoesNotRun,
          '.'.join((
              'process branch main', 'compile chromite protos',
              'create gerrit change for [CLEANUP]/chromiumos_workspace/chromite'
          )),
      ),
      api.buildbucket.build(
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project='chromeos',
                  bucket='staging',
                  builder='staging-ProtoDoctor',
              ),
          ),
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-gitiles-triggers',
      api.scheduler(triggers=[
          triggers_pb2.Trigger(buildbucket=buildbucket_trigger),
      ]),
      api.post_check(post_process.StepException, 'validate triggers'),
      api.post_check(post_process.SummaryMarkdown, 'No Gitiles triggers found'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'non-proto-trigger',
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_chromite),
      ]),
      api.post_check(post_process.StepException, 'validate triggers'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Gitiles trigger in non-proto repo:.*'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'first-branch-fails-second-branch-runs',
      api.properties(expected_cl_owners=['sundar@google.com']),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_release_branch),
      ]),
      api.step_data('process branch main.repo init', retcode=1),
      # Double-check that the main branch comes before the release branch.
      api.post_check(post_process.PropertyEquals, 'refs',
                     [MAIN_REF, release_ref]),
      api.post_check(post_process.StepException,
                     f'process branch {MAIN_BRANCH}'),
      api.post_check(post_process.StepSuccess,
                     f'process branch {release_branch}'),
      # Some necessary step data to prevent unexpected failures.
      api.gerrit.set_query_changes_response(
          f'process branch {release_branch}.wait for open cls', [],
          gerrit_api.EXTERNAL_HOST),
      api.gerrit.set_query_changes_response(
          f'process branch {release_branch}.wait for open cls', [],
          gerrit_api.INTERNAL_HOST),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'polling-timeout',
      api.properties(expected_cl_owners=['sundar@google.com']),
      api.scheduler(
          triggers=[triggers_pb2.Trigger(gitiles=gitiles_trigger_main)]),
      # Make the time-step large enough to query once, but not twice.
      api.time.step(.7 * DEFAULT_OPEN_CL_POLL_TIMEOUT_SECS),
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [cq_active_cl],
          gerrit_api.EXTERNAL_HOST),
      api.gerrit.set_query_changes_response(
          'process branch main.wait for open cls', [cq_active_cl],
          gerrit_api.INTERNAL_HOST),
      api.post_check(post_process.StepFailure,
                     'process branch main.wait for open cls'),
      api.post_check(post_process.SummaryMarkdown,
                     'Timed out waiting for CQ to finish.'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'no-expected-cl-owners-specified',
      api.scheduler(
          triggers=[triggers_pb2.Trigger(gitiles=gitiles_trigger_main)]),
      api.post_check(
          post_process.SummaryMarkdown,
          'Cannot find old ProtoDoctor CLs, because expected CL owners were '
          'not specified.'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
