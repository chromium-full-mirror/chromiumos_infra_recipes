# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the PUpr generator.

PUpr is a general uprev pipeline that automatically creates uprev CLs for new
software patches, such as ebuild uprevs and SDK uprevs. It tags appropriate
reviewers, sets CL labels, and handles existing uprev CLs. Think of it as the
CrOS autoroller.

PUpr is usually triggered via LUCI Scheduler gitiles triggers in response to
package releases. It can also be scheduled to run on a cron.

See go/pupr and go/pupr-generator for rationale, design decisions, and usage
instructions.
"""

import re
from functools import cached_property
from typing import List
from typing import NamedTuple
from typing import Optional
from urllib import parse

from RECIPE_MODULES.chromeos.git.api import Reference
from RECIPE_MODULES.chromeos.pupr.api import HASHTAG_FREEZE_RETRIES
from RECIPE_MODULES.chromeos.pupr_gerrit_interface.api import ProjectsByRemote
from RECIPE_MODULES.chromeos.pupr_local_uprev.api import UPREV_VERSION_LABEL
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo
from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import CronTrigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import GitilesTrigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import Trigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import WebUITrigger
from PB.recipe_engine import result
# pylint: disable=unused-import
from PB.recipes.chromeos.generator import ABANDON
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import DO_NOTHING
from PB.recipes.chromeos.generator import DRY_RUN
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import GeneratorProperties
from PB.recipes.chromeos.generator import GitilesFetchInfo
from PB.recipes.chromeos.generator import NO_RETRY
from PB.recipes.chromeos.generator import OUTDATED_ABANDON
from PB.recipes.chromeos.generator import OUTDATED_DO_NOTHING
from PB.recipes.chromeos.generator import OUTDATED_LEAVE_COMMENT
from PB.recipes.chromeos.generator import RETRY_LATEST_OR_LATEST_PINNED
from PB.recipes.chromeos.generator import RetryRef
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from PB.recipes.chromeos.generator import UprevTargetKind
from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'cros_build_api',
    'cros_cq_depends',
    'cros_sdk',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'git_cl',
    'git_footers',
    'gitiles',
    'naming',
    'pupr',
    'pupr_gerrit_interface',
    'pupr_local_uprev',
    'repo',
    'src_state',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GeneratorProperties


def RunSteps(api: RecipeApi,
             properties: GeneratorProperties) -> result.RawResult:
  summary = GeneratorRun(api, properties).run()
  return result.RawResult(status=common.SUCCESS, summary_markdown=summary)


class PolicyInfo(NamedTuple):
  policy: BranchPolicy
  branch: str = ''
  reference: Optional[Reference] = None


class GeneratorRun:
  """A single run of a Generator builder."""

  def __init__(self, api: RecipeApi, properties: GeneratorProperties):
    """Initialize the builder."""
    self.m = api
    self.properties = properties

    self.workspace_path: Optional[Path] = None
    self._policy: Optional[BranchPolicy] = None
    self._modified_projects: Optional[List[ProjectInfo]] = None

    # If we see gitiles_info populated in the recipe properties, we will be
    # performing a fetch from the Gitiles API for the package's target uprev
    # version. This information will be used in branch determination and sent to
    # the uprev handler.
    self.target_version_from_gitiles = None

  @property
  def _is_package_uprevver(self) -> bool:
    """Return whether this generator run is a package uprevver."""
    return self.properties.uprev_target_kind is UprevTargetKind.PACKAGE

  @property
  def _is_sdk_uprevver(self) -> bool:
    """Return whether this generator run is an SDK uprevver."""
    return self.properties.uprev_target_kind is UprevTargetKind.SDK

  @cached_property
  def triggers(self) -> List[Trigger]:
    """Get this run's triggers, all of which have the gitiles field set."""
    if self._has_cron_trigger:
      return [
          Trigger(gitiles=GitilesTrigger(ref=self.properties.retry_ref.ref))
      ]
    return self._raw_triggers

  @property
  def target_package_versions(self
                             ) -> List[UprevVersionedPackageRequest.GitRef]:
    """Return the package versions to try to uprev to.

    Raises:
        InfraFailure: If this generator does not uprev packages.
    """
    assert self._is_package_uprevver
    return [
        UprevVersionedPackageRequest.GitRef(
            repository=parse.urlparse(trigger.gitiles.repo).path,
            ref=trigger.gitiles.ref,
            revision=(self.target_version_from_gitiles or
                      trigger.gitiles.revision)) for trigger in self.triggers
    ]

  @property
  def retry_only_run(self) -> bool:
    """Check whether this is a retry-only run."""
    return self._has_cron_trigger

  @property
  def cpvs(self) -> List[str]:
    """Get the category-package-version for this build's packages."""
    assert self._is_package_uprevver
    return [
        self.m.naming.get_package_title(package)
        for package in self.properties.packages
    ]

  @property
  def policy(self) -> BranchPolicy:
    """Get the branch policy that applies to this build. See generator.proto."""
    assert self._policy is not None
    return self._policy

  def set_policy(self, policy: BranchPolicy):
    """Set the policy for this build, and report it as a step."""
    self.m.easy.set_properties_step(policy=MessageToDict(policy))
    self._policy = policy

  @property
  def topic(self) -> str:
    """Get the topic to use for all generated CLs."""
    if self.policy and self.policy.topic:
      return self.policy.topic
    if self.properties.topic:
      return self.properties.topic
    if self._is_package_uprevver:
      return self.cpvs[0]
    if self._is_sdk_uprevver:  # pragma: nocover
      return 'cros_sdk'
    raise InfraFailure('Not sure how to generate topic')  # pragma: nocover

  @cached_property
  def _projects_by_remote(self) -> ProjectsByRemote:
    """Organize projects relevant to this run by remote."""
    return self.m.pupr_gerrit_interface.sort_projects_by_remote(
        self._repo_projects)

  @property
  def _repo_projects(self) -> List[ProjectInfo]:
    """Return all repo projects with code that this PUpr uprevs."""
    if self.retry_only_run:
      return [
          ProjectInfo(
              remote=self.properties.retry_ref.remote,
              name=self.properties.retry_ref.name,
              branch=self.properties.retry_ref.ref,
              rrev=self.properties.retry_ref.ref,
              path=self.properties.retry_ref.path,
          )
      ]
    assert self._modified_projects is not None
    return self._modified_projects

  def make_summary(self, msg: str) -> str:
    if self.retry_only_run:
      return '[retry-only] ' + msg
    return msg

  def run(self) -> str:
    """Run the Generator."""
    self.m.cros_source.configure_builder(self.m.src_state.gitiles_commit,
                                         self.m.src_state.gerrit_changes)
    self.workspace_path = self.m.cros_source.workspace_path

    self._validate_properties()
    self._validate_triggers()
    self.m.pupr_local_uprev.set_generator_attributes(
        additional_commit_message=self.properties.additional_commit_message,
        allow_partial_uprev=self.properties.allow_partial_uprev,
        build_targets=self.properties.build_targets,
        packages=self.properties.packages,
    )
    self.m.pupr_gerrit_interface.rebase_before_retry = self.properties.rebase_before_retry

    policy_info = self.select_policy()
    self.set_policy(policy_info.policy)
    if self.policy.ignore:
      self.m.step.empty('policy set to ignore')
      return self.make_summary('ignore by policy')

    with self.m.cros_source.checkout_overlays_context(), \
        self.m.cros_sdk.cleanup_context():
      self.m.cros_source.ensure_synced_cache(manifest_branch_override='main')

      self.checkout_branch(policy_info)

      if self.m.cq.active or self.m.src_state.gerrit_changes:
        self.apply_gerrit_changes()

      if self.properties.init_sdk:
        with self.m.context(cwd=self.workspace_path):
          self.m.cros_sdk.create_chroot()

      if not self.retry_only_run:
        self._modified_projects = self.create_local_uprev()
        if self._modified_projects is None:
          return self.make_summary('no modified projects')

      open_changes = self.m.pupr_gerrit_interface.find_open_uprev_cls(
          self._projects_by_remote, self.topic)
      do_open_cls_remain = self.m.pupr_gerrit_interface.handle_open_changes(
          open_changes, self._projects_by_remote, self.policy, self.topic,
          self.retry_only_run)

      if not self.retry_only_run:
        return self.m.pupr_gerrit_interface.create_uprev_cls(
            self._repo_projects, open_changes, do_open_cls_remain, self.policy,
            self.topic)
      return self.make_summary('success')

  def create_local_uprev(self) -> Optional[List[ProjectInfo]]:
    """Create and commit uprevs on the local filesystem.

    Returns:
      If the uprev is successful, a list of repo projects with code changes.
      Otherwise, None, signifying that the build should terminate immediately.
    """
    if self._is_package_uprevver:
      return self.m.pupr_local_uprev.uprev_packages(
          self.target_package_versions, self.topic)
    if self._is_sdk_uprevver:
      return self.m.pupr_local_uprev.uprev_sdk()
    raise InfraFailure('Not sure how to uprev.')  # pragma: nocover

  def _validate_properties(self):
    """Ensure the input properties look OK.

    Raises:
      StepFailure: if there are any issues with the input properties.
    """
    with self.m.step.nest('validate properties') as presentation:
      if self._is_package_uprevver and not self.properties.packages:
        raise StepFailure('must set packages to uprev for a package uprevver')

      # Retrieve version information from Gitiles API.
      if self.properties.HasField('gitiles_info'):
        if not (self.properties.gitiles_info.host and
                self.properties.gitiles_info.project and
                self.properties.gitiles_info.path):
          raise StepFailure('gitiles fetch requested with no fetch '
                            'infomation supplied')

      for policy in self.properties.branch_policies:
        if not policy.pattern:
          raise StepFailure('must specify pattern')
        if not policy.reviewers:
          raise StepFailure('need at least one reviewer')

        for reviewer in policy.reviewers:
          if not reviewer.email:
            raise StepFailure('must set reviewer email')

      presentation.step_text = 'all properties good'

  def _validate_triggers(self):
    """Check whether the build's triggers are OK.

    Raises:
      StepFailure: If no triggers are found, or if any non-cron, non-gitiles
      triggers are found.
    """
    with self.m.step.nest('validate triggers') as presentation:
      if not self.triggers:
        raise StepFailure('found no triggers')
      if self._has_cron_trigger:
        presentation.step_text = 'has cron trigger, running in retry-only mode'
      else:
        for trigger in self.triggers:
          if not trigger.HasField('gitiles'):
            raise StepFailure('found non-gitiles trigger: %r' % trigger)

        presentation.step_text = 'found {} good triggers'.format(
            len(self.triggers))
        presentation.logs['list of triggers'] = map(MessageToJson,
                                                    self.triggers)

  @property
  def _raw_triggers(self) -> List[Trigger]:
    """Get the triggers which actually launched this run."""
    return self.properties.triggers or self.m.scheduler.triggers

  @property
  def _has_cron_trigger(self) -> bool:
    """Check whether any of this build's triggers is a cron trigger."""
    return any(trigger.HasField('cron') for trigger in self._raw_triggers)

  def select_policy(self) -> PolicyInfo:
    """Return the trigger policy that applies to this build.

    This will affect which branch the build will use. If the input properties
    specify gitiles_info, then we will determine the branch based on information
    returned by the Gitiles API. Otherwise, use the gitiles.ref seen in the
    trigger.

    Raises:
      StepFailure: If more than one applicable trigger is selected.
    """
    with self.m.step.nest('select policy'):
      trigger_policies: List[PolicyInfo] = []
      for trigger in self.triggers:
        # Retrieve version information from Gitiles API.
        if self.properties.HasField('gitiles_info'):
          gitiles_response = self.m.gitiles.get_file(
              str(self.properties.gitiles_info.host),
              str(self.properties.gitiles_info.project),
              str(self.properties.gitiles_info.path),
              ref=str(trigger.gitiles.ref),
              test_output_data='MTIzLjQ1Ni43ODkuMAo=').decode()
          if gitiles_response:
            self.target_version_from_gitiles = gitiles_response.strip()

        tag = self.target_version_from_gitiles or trigger.gitiles.ref
        policy_info = self._get_policy_info_for_tag(tag)
        if policy_info not in trigger_policies:
          trigger_policies.append(policy_info)
      # If we match more than one policy with the triggers, that is an error.
      # For Chrome, we are launched with properties.triggers, for exactly one
      # version.  See http://shortn/_qWgYUlVY6X in trigger_official_builds().
      if len(trigger_policies) > 1:
        raise StepFailure('too many triggers')
      return trigger_policies.pop()

  def _get_policy_info_for_tag(self, tag: str) -> PolicyInfo:
    """Find the applicable policy for the given Git tag.

    The policy used is the first policy where policy.pattern matches the tag,
    and either:
    - the substitution result is the empty string (default branch, aka legacy),
      or
    - a remote reference is in manifest-internal for the substitution result.

    Args:
      tag: Version information used to generate the branch name.
        (e.g. 123.456.789.0)

    Returns:
      PolicyInfo namedtuple with:
      - policy: The selected policy.
      - branch: The branch to checkout. Empty if there is no branch to checkout.
      - reference: The reference that matched, or None.
    """
    manifest = self.m.src_state.internal_manifest
    with self.m.context(cwd=manifest.path):
      for policy in self.properties.branch_policies:
        if re.match(policy.pattern, tag):
          query = re.sub(policy.pattern, policy.repl, tag)
          if not query:
            return PolicyInfo(policy)
          refs = self.m.git.ls_remote([query])
          if len(refs) == 1:
            ref = refs[0]
            return PolicyInfo(policy, ref.ref.split('/')[-1], ref)
          if refs:
            raise StepFailure('multiple branches matched {}: {}'.format(
                query, ' '.join(x.ref for x in refs)))
          # If we found no references, this policy does not apply.

      raise StepFailure('No matching policy found for tag {}'.format(tag))

  def checkout_branch(self, policy_info: PolicyInfo):
    """Check out the appropriate branch based on the selected policy."""
    with self.m.step.nest('checkout branch') as pres:
      if policy_info.branch:
        assert policy_info.reference is not None
        pres.step_text = 'using {} {}'.format(policy_info.branch,
                                              policy_info.reference.hash)
        self.m.cros_source.checkout_branch(
            self.m.src_state.internal_manifest.url, policy_info.branch)
      else:
        pres.step_text = 'using default branch'

  def apply_gerrit_changes(self):
    """Cherry-pick changes for CQ runs, and prevent production changes.

    If there are gerrit_changes to apply, log the chosen policy, and then
    override the policy so that we do not submit, abandon, or comment on
    anything.

    Use case: Developer is working on the versioned uprev code for a package,
    such as Chrome, and wants to test the changes prior to landing them in
    chromite.  While launching a build with the correct policies and triggers is
    difficult in CQ, it is rather straightforward for the dev to manually launch
    the build with "correct" inputs.  On the other hand, we should not produce
    production effects with uncommitted changes.
    """
    with self.m.step.nest('apply gerrit changes'):
      if self.m.src_state.gerrit_changes:
        self.m.cros_source.apply_gerrit_changes(self.m.src_state.gerrit_changes)
      with self.m.step.nest('update policy'):
        user = self.m.buildbucket.build.created_by.replace('user:', '', 1)
        self.m.easy.set_properties_step(
            original_policy=MessageToDict(self.policy))
        del self.policy.reviewers[:]
        self.policy.reviewers.add().email = user
        self.policy.existing_cls_policy = ABANDON
        self.policy.no_existing_cls_policy = ABANDON
        self.policy.outdated_cls_policy = OUTDATED_DO_NOTHING
        self.policy.retry_cl_policy = NO_RETRY
        self.policy.topic = '{}-{}'.format('testing', self.topic)
        self.m.easy.set_properties_step(policy=MessageToDict(self.policy))


def GenTests(api: RecipeTestApi):

  def _policy(**kwargs):
    """Create a BranchPolicy, with defaults."""
    kwargs.setdefault('pattern', '.*')
    kwargs.setdefault('ignore', False)
    kwargs.setdefault('reviewers', [
        Reviewer(email='evanhernandez@chromium.org'),
        Reviewer(email='chromeos-continuous-integration-team@google.com')
    ])
    kwargs.setdefault('existing_cls_policy', DO_NOTHING)
    kwargs.setdefault('no_existing_cls_policy', DO_NOTHING)
    kwargs.setdefault('outdated_cls_policy', OUTDATED_DO_NOTHING)
    kwargs.setdefault('retry_cl_policy', NO_RETRY)
    return BranchPolicy(**kwargs)

  def _props(**kwargs):
    """Create GeneratorProperties, with defaults."""
    if not kwargs.get('packages'):
      kwargs.setdefault(
          'packages',
          [PackageInfo(category='chromeos-base', package_name='chromite')])
    kwargs.setdefault('uprev_target_kind', UprevTargetKind.PACKAGE)
    kwargs.setdefault('build_targets', [BuildTarget(name='build_target')])
    kwargs.setdefault('branch_policies', [_policy()])
    kwargs.setdefault('gitiles_info', None)
    return api.properties(GeneratorProperties(**kwargs))

  chromite_gitiles_trigger = Trigger(
      id='123',
      gitiles=GitilesTrigger(
          repo='chromiumos/chromite',
          ref=api.src_state.default_ref,
          revision='deadbeef',
      ),
  )

  def _with_infos(name: str, *args, **kwargs):
    return api.test(
        name,
        api.repo.project_infos_step_data('commit uprev', data=[
            dict(project='overlay'),
        ], iteration=1),
        api.repo.project_infos_step_data(
            'commit uprev', data=[
                dict(project='private-overlay', remote='cros-internal'),
            ], iteration=2), *args, **kwargs)

  yield api.test(
      'ignore-policy',
      _props(branch_policies=[_policy(ignore=True)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'policy set to ignore'),
      api.post_check(post_process.DoesNotRun, 'commit uprev.repo forall'),
  )

  yield _with_infos(
      'with-uprev-do-nothing-policy',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-do-nothing-policy-init-sdk',
      _props(init_sdk=True),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-dry-run-policy',
      _props(branch_policies=[_policy(existing_cls_policy=DRY_RUN)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-full-run-policy',
      _props(branch_policies=[_policy(existing_cls_policy=FULL_RUN)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-abandon-policy',
      _props(branch_policies=[_policy(existing_cls_policy=ABANDON)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-abandon-outdated-policy',
      _props(branch_policies=[_policy(outdated_cls_policy=OUTDATED_ABANDON)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-abandon-no-nothing-policy',
      _props(branch_policies=[_policy(
          outdated_cls_policy=OUTDATED_DO_NOTHING)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-submit-policy',
      _props(branch_policies=[
          _policy(no_existing_cls_policy=SUBMIT, existing_cls_policy=SUBMIT)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-comment-outdated-policy',
      _props(
          branch_policies=[_policy(
              outdated_cls_policy=OUTDATED_LEAVE_COMMENT)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'fail-validate-props-on-gitiles-fetch-info',
      _props(gitiles_info=GitilesFetchInfo()),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'no-matching-policy',
      _props(branch_policies=[]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.DoesNotRun, 'set policy'),
      status='FAILURE',
  )

  yield api.test(
      'no-packages',
      api.properties(uprev_target_kind=UprevTargetKind.PACKAGE),
      status='FAILURE',
  )

  yield api.test(
      'no-reviewers',
      _props(branch_policies=[_policy(reviewers=None)]),
      api.git.diff_check(True),
      status='FAILURE',
  )

  yield api.test(
      'blank-reviewer',
      _props(branch_policies=[_policy(reviewers=[{}])]),
      api.git.diff_check(True),
      status='FAILURE',
  )

  yield api.test(
      'non-gitiles-triggers',
      _props(),
      api.scheduler(triggers=[
          Trigger(id='456', webui=WebUITrigger()),
      ]),
      api.git.diff_check(True),
      status='FAILURE',
  )

  yield api.test(
      'without-uprev',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.step_data(
          'try uprev chromeos-base/chromite.uprev versioned package'
          '.read output file', api.file.read_raw(content='{}')),
  )

  yield api.test(
      'one-change',
      _props(branch_policies=[_policy(existing_cls_policy=FULL_RUN)]),
      # Only one changed project.
      api.repo.project_infos_step_data('commit uprev', data=[
          dict(project='overlay'),
      ], iteration=1),
      api.repo.project_infos_step_data('commit uprev', data=[
          dict(project='overlay'),
      ], iteration=2),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'no-changes',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(False),
  )

  yield _with_infos(
      'with-gerrit-changes', _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun,
                     'apply gerrit changes.update policy'),
      api.test_util.test_build(
          revision=None, extra_changes=[
              GerritChange(host='chromium-review.googlesource.com', change=1234)
          ], created_by='user:lamontjones@chromium.org').build)

  yield _with_infos(
      'with-gerrit-changes_with_revision_override',
      _props(
          branch_policies=[_policy(pattern=r'.*\s*')],
          gitiles_info=GitilesFetchInfo(host='chromium.googlesource.com',
                                        project='chrome/src',
                                        path='foo/bar.txt')),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun,
                     'apply gerrit changes.update policy'),
      api.post_check(
          post_process.MustRun, 'select policy.fetch gitiles file.'
          'curl https://chromium.googlesource.com'
          '/chrome/src/+/refs/heads/main/foo/bar.txt?format=TEXT'),
      api.test_util.test_build(
          revision=None, extra_changes=[
              GerritChange(host='chromium-review.googlesource.com', change=1234)
          ], created_by='user:lamontjones@chromium.org').build)

  yield _with_infos(
      'cq-active', _props(), api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True), api.cq(run_mode=api.cq.FULL_RUN),
      api.post_check(post_process.MustRun,
                     'apply gerrit changes.update policy'),
      api.test_util.test_build(revision=None, extra_changes=[],
                               created_by='project:chromiumos').build)

  # Set up for testing chromeos-base/chromeos-chrome trigger filtering.
  package_chrome = PackageInfo(category='chromeos-base',
                               package_name='chromeos-chrome')
  trigger_prop = MessageToDict(
      Trigger(
          id='123',
          gitiles=GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/tags/79.0.3945.20',
              revision='83a1812dddfc24f604d92bf61ad58efe9227a6fc',
          ),
      ))

  trigger_prop2 = MessageToDict(
      Trigger(
          id='456',
          gitiles=GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref=api.src_state.default_ref,
              revision='0572e38c2b2073613ee5b861a9165335621bf54a',
          ),
      ))

  # Testing direct invocation, that is, not invoked with properties from
  # a gitiles poller through api.scheduler.
  yield api.test(
      'invoked-directly',
      _props(
          packages=[package_chrome], branch_policies=[
              _policy(reviewers=[Reviewer(email='dburger@chromium.org')])
          ]),
      api.properties(triggers=[trigger_prop]),
  )

  branch_policy = _policy(
      pattern='refs/tags/([0-9]*).*',
      repl=r'release-R\1-*.B',
      reviewers=[Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=DRY_RUN,
      existing_cls_policy=DRY_RUN,
      outdated_cls_policy=OUTDATED_ABANDON,
  )
  no_pattern_policy = _policy(
      pattern='',
      repl=r'release-R\1-*.B',
      reviewers=[Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=DRY_RUN,
      existing_cls_policy=DRY_RUN,
      outdated_cls_policy=OUTDATED_ABANDON,
  )

  yield _with_infos(
      'branch-policies',
      api.properties(triggers=[trigger_prop]),
      _props(packages=[package_chrome], branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'checkout branch.checkout branch release-R79-*.B'),
  )

  yield _with_infos(
      'branch-policies-multiple-triggers',
      api.properties(triggers=[trigger_prop] * 2),
      _props(packages=[package_chrome], branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'checkout branch.checkout branch release-R79-*.B'),
  )

  yield api.test(
      'branch-policies-multiple-trigger-policies',
      api.properties(triggers=[trigger_prop, trigger_prop2]),
      _props(packages=[package_chrome],
             branch_policies=[branch_policy, _policy()]),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      status='FAILURE',
  )

  yield api.test(
      'branch-policies-no-pattern',
      api.properties(triggers=[trigger_prop]),
      _props(packages=[package_chrome], branch_policies=[no_pattern_policy]),
      api.post_check(post_process.DoesNotRun, 'select policy.git ls-remote'),
      status='FAILURE',
  )

  yield api.test(
      'branch-policies-default-branch',
      api.properties(triggers=[trigger_prop]),
      _props(
          packages=[package_chrome], branch_policies=[
              BranchPolicy(pattern='.*', repl='',
                           reviewers=[Reviewer(email='a@example.com')])
          ]),
      api.post_check(post_process.DoesNotRun, 'select policy.git ls-remote'),
  )

  yield api.test(
      'branch-policies-multi-ref',
      api.properties(triggers=[trigger_prop]),
      _props(packages=[package_chrome], branch_policies=[branch_policy]),
      api.step_data(
          'select policy.git ls-remote',
          stdout=api.raw_io.output_text('\n'.join([
              '9ed37bc6f515ef0ef42949d9f23e1180432649f5\t'
              'refs/remotes/cros-internal/release-R79-5555.B',
              'f3ecd792bc4822dd6686313478099b8eb3df7e55\t'
              'refs/remotes/cros-internal/release-R79-9999.B',
              '',
          ]))),
      status='FAILURE',
  )

  yield _with_infos(
      'multiple-packages', api.properties(triggers=[trigger_prop]),
      _props(
          packages=[
              package_chrome,
              PackageInfo(category='chromeos-base',
                          package_name='chromeos-lacros'),
          ],
          topic='chromeos-base/new-topic-name',
      ), api.git.diff_check(True),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-chrome'),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-lacros'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in overlay.write commit message', [
              '.*', '.*', '.*', '.*', '.*', '.*',
              r'(.|\n)*Pupr-Upstream-Versions: \[\{\"ref\": \"refs/tags/79.0.3945.20\", \"repository\": \"/chromium/src\", \"revision\": \"83a1812dddfc24f604d92bf61ad58efe9227a6fc\"\}\](.|\n)*',
              '.*'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'generate CLs.create gerrit change for src/overlay.git_cl upload',
          ['--topic', 'chromeos-base/new-topic-name']))

  changes = [
      GerritChange(change=1, host='chromium-review.googlesource.com'),
      GerritChange(change=2, host='chromium-review.googlesource.com'),
  ]

  gerrit_changes_json = [
      {
          '_number': 1,
          'change_number': 1,
          'project': 'chromium/src',
          'host': 'chromium-review.googlesource.com',
      },
      {
          '_number': 2,
          'change_number': 2,
          'project': 'chromium/src',
          'host': 'chromium-review.googlesource.com',
      },
  ]

  value_dict = {
      1: {
          'change_id': 1,
          'created': '2020-10-22 18:54:00.000000000',
          'messages': [
              {
                  'message':
                      'Quote: Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
                  'date':
                      '2020-10-26T18:54:00Z',
              },
              {
                  'message': 'Patch Set 3:\n\nCV is trying the patch...',
                  'date': '2020-10-24T18:54:00Z',
                  # CV adds timestamp to the suffix of each autogenerated:cv:* tag.
                  # This is only for making every tags unique, but not intended to store useful information.
                  # For this reason, those parts in the test data are filled with fake values.
                  'tag': 'autogenerated:cv:full-run:1000000001'
              },
              {
                  'message':
                      'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
                  'date':
                      '2020-10-25T18:54:00Z',
                  'tag':
                      'autogenerated:cv:full-run:1000000002'
              }
          ],
          'revision_info': {
              'ref': 'refs/change/foo',
          },
      },
      2: {
          'change_id': 2,
          'created': '2020-10-23 18:54:00.000000000',
      },
  }

  yield _with_infos(
      'no-most-recent-merged-cl',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [], 'https://chromium-review.googlesource.com'),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chrome-internal host (within 30 days)',
          [], 'https://chrome-internal-review.googlesource.com'),
      api.post_check(post_process.DoesNotRun, 'outdated CLs'),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_infos(
      'with-retry-policy',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=DRY_RUN, no_existing_cls_policy=DRY_RUN)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
  )

  yield _with_infos(
      'with-retry-policy-but-no-open-changes',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=DRY_RUN, no_existing_cls_policy=DRY_RUN)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host', [],
          'https://chromium-review.googlesource.com'),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chrome-internal host', [],
          'https://chrome-internal-review.googlesource.com'),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
      api.post_check(
          post_process.DoesNotRun,
          r'apply retry policy RETRY_LATEST_OR_LATEST_PINNED\.retry CL .*'),
      api.post_check(post_process.MustRun, 'generate CLs'),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_infos(
      'with-retry-policy-but-retries-frozen',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=DRY_RUN, no_existing_cls_policy=DRY_RUN)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          [GerritChange(change=1, host='chromium-review.googlesource.com')], {
              1: {
                  'change_id': 777,
                  'created': '2020-10-22 18:54:00.000000000',
                  'hashtags': [HASHTAG_FREEZE_RETRIES],
              }
          }),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
      api.post_check(
          post_process.DoesNotRunRE,
          r'apply retry policy RETRY_LATEST_OR_LATEST_PINNED\.retry CL .*'),
      api.post_check(post_process.MustRun, 'generate CLs'),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_infos(
      'with-retry-policy-but-no-retry-cl-identified',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=DRY_RUN, no_existing_cls_policy=DRY_RUN)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
      api.post_check(
          post_process.DoesNotRun,
          r'apply retry policy RETRY_LATEST_OR_LATEST_PINNED\.retry CL .*'),
      api.post_check(post_process.MustRun, 'generate CLs'),
      api.post_process(post_process.DropExpectation),
  )

  retry_ref = RetryRef(
      remote='cros',
      path='src/third_party/chromiumos-overlay',
      name='chromiumos/overlays/chromiumos-overlay',
      ref='refs/heads/main',
  )

  yield api.test(
      'no-triggers',
      _props(),
      api.scheduler(triggers=[]),
      api.git.diff_check(True),
      status='FAILURE',
  )

  revision = '83a1812dddfc24f604d92bf61ad58efe9227a6fc'
  value_dict = {
      1: {
          'change_id': 1,
          'created': '2020-10-22 18:54:00.000000000',
          'messages': [{
              'message':
                  'Quote: Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-26T18:54:00Z',
          }, {
              'message': 'Patch Set 3:\n\nCV is trying the patch...',
              'date': '2020-10-24T18:54:00Z',
              'tag': 'autogenerated:cv:full-run:1000000001'
          }, {
              'message':
                  'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-25T18:54:00Z',
              'tag':
                  'autogenerated:cv:full-run:1000000002'
          }],
          'revision_info': {
              'ref': 'refs/change/foo',
              'commit': {
                  'message':
                      'a quick description\n\nChange-Id: deadbeef\n\nPupr-Upstream-Versions: [{"ref": "refs/tags/79.0.3945.20", "repository": "/chromium/src", "revision": "'
                      + revision + '"}]',
              },
          },
      },
      2: {
          'change_id': 2,
          'created': '2020-10-23 18:54:00.000000000',
      },
  }

  yield api.test(
      'cron-trigger',
      _props(
          branch_policies=[
              _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                      existing_cls_policy=DRY_RUN,
                      no_existing_cls_policy=DRY_RUN)
          ], retry_ref=retry_ref),
      api.scheduler(triggers=[Trigger(cron=CronTrigger(generation=-1))]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
      api.post_check(
          post_process.DoesNotRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.commit uprev.commit in overlay.write commit message'
      ),
  )

  yield api.test(
      'cron-trigger-rebase',
      _props(
          branch_policies=[
              _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                      existing_cls_policy=DRY_RUN,
                      no_existing_cls_policy=DRY_RUN)
          ], retry_ref=retry_ref, rebase_before_retry=True),
      api.scheduler(triggers=[Trigger(cron=CronTrigger(generation=-1))]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.get CL 1 description',
          changes, value_dict),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          'chromium-review.googlesource.com', 1, 'current', False),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']),
      api.post_check(
          post_process.StepSuccess,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1'),
      # Commit message should contain the same version label as the original.
      # The change should be uploaded as a new patch set for the same Change-Id.
      api.post_check(
          post_process.StepCommandRE,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.commit uprev.commit in overlay.write commit message',
          [
              '.*', '.*', '.*', '.*', '.*', '.*',
              r'(.|\n)*' + UPREV_VERSION_LABEL + '.*' + revision +
              r'(.|\n)*Change-Id: deadbeef(.|\n)*', '.*'
          ]),
      api.post_check(post_process.MustRunRE,
                     r'.*upload patch set for Change-Id 1\.git_cl upload'))

  value_dict = {
      1: {
          'change_id': 1,
          'created': '2020-10-22 18:54:00.000000000',
          'messages': [{
              'message':
                  'Quote: Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-26T18:54:00Z',
          }, {
              'message': 'Patch Set 3:\n\nCV is trying the patch...',
              'date': '2020-10-24T18:54:00Z',
              'tag': 'autogenerated:cv:full-run:1000000001'
          }, {
              'message':
                  'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-25T18:54:00Z',
              'tag':
                  'autogenerated:cv:full-run:1000000002'
          }],
          'revision_info': {
              'ref': 'refs/change/foo',
          },
      },
      2: {
          'change_id': 2,
          'created': '2020-10-23 18:54:00.000000000',
          'messages': [{
              'message':
                  'Quote: Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-26T18:54:00Z',
          }, {
              'message': 'Patch Set 3:\n\nDry run: CV is trying the patch...',
              'date': '2020-10-24T18:54:00Z',
              'tag': 'autogenerated:cv:dry-run:1000000001'
          }, {
              'message': 'Patch Set 3:\n\nThis CL has passed the run',
              'date': '2020-10-25T18:54:00Z',
              'tag': 'autogenerated:cv:dry-run:1000000002'
          }],
          'revision_info': {
              'ref': 'refs/change/foo',
          },
      },
  }

  yield api.test(
      'cron-trigger-discard-before-passed-dry-run',
      _props(
          branch_policies=[
              _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                      existing_cls_policy=DRY_RUN,
                      no_existing_cls_policy=FULL_RUN,
                      outdated_cls_policy=OUTDATED_ABANDON)
          ], retry_ref=retry_ref),
      api.scheduler(triggers=[Trigger(cron=CronTrigger(generation=-1))]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response('', changes, value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          changes, value_dict),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
  )

  yield api.test(
      'no-merged-changes-warning',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(
          post_process.StepWarning,
          'examine outdated CLs.merged CLs from chrome-internal host (within 30 days)'
      ),
  )

  yield api.test(
      'sdk-uprev',
      _props(uprev_target_kind=UprevTargetKind.SDK),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.StepException, 'uprev sdk'),
      status='INFRA_FAILURE',
  )
