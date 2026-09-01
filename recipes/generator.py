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
from __future__ import annotations

import abc
import contextlib
import dataclasses
import re
from typing import Generator
import urllib

from google.protobuf import json_format
from PB.chromite.api import packages as packages_pb2
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.gerrit import gerrit as gerrit_pb2
from PB.recipe_modules.chromeos.pupr_local_uprev import (pupr_local_uprev as
                                                         pupr_local_uprev_pb2)
from PB.recipes.chromeos import generator as generator_pb2
from recipe_engine import config_types
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine.engine_types import StepPresentation
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet
from RECIPE_MODULES.chromeos.git import api as git_api
from RECIPE_MODULES.chromeos.pupr import api as pupr_api
from RECIPE_MODULES.chromeos.pupr.api import Result
from RECIPE_MODULES.chromeos.pupr_gerrit_interface import api as pupr_gerrit_interface_api
from RECIPE_MODULES.chromeos.pupr_local_uprev import api as pupr_local_uprev_api
from RECIPE_MODULES.chromeos.repo import api as repo_api

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'chrome',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'easy',
    'gerrit',
    'git',
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


PROPERTIES = generator_pb2.GeneratorProperties


def RunSteps(
    api: recipe_api.RecipeApi,
    properties: generator_pb2.GeneratorProperties) -> result_pb2.RawResult:
  status, summary = GeneratorRun(api, properties).run()
  return result_pb2.RawResult(status=status, summary_markdown=summary)


@dataclasses.dataclass
class PolicyInfo:
  policy: generator_pb2.BranchPolicy
  branch: str = ''
  reference: git_api.Reference | None = None

  @property
  def target_branch(self) -> str:
    """The branch to query on Gerrit (defaults to 'main')."""
    return self.branch or 'main'


class UprevTargetHandler(abc.ABC):
  """Abstract base handler for kind-specific uprev behaviors."""

  def __init__(self, run: GeneratorRun) -> None:
    self.run = run

  @property
  def m(self) -> recipe_api.RecipeApi:
    return self.run.m

  @property
  def properties(self) -> generator_pb2.GeneratorProperties:
    return self.run.properties

  @abc.abstractmethod
  def validate_properties(self) -> None:
    """Validate target-specific properties."""

  @abc.abstractmethod
  def get_default_topic(self) -> str:
    """Return the default topic for generated CLs."""

  def get_policy_repo_url(self, default_url: str) -> str:
    """Return the git repository URL used for branch policy matching."""
    return default_url

  def checkout_branch(self, policy_info: PolicyInfo) -> None:
    """Check out the target branch for this uprev."""
    self.m.cros_source.checkout_branch(self.m.src_state.internal_manifest.url,
                                       policy_info.branch)

  def checkout_default_branch(self, pres: StepPresentation) -> None:
    """Handle checkout when no specific branch was selected."""
    pres.step_text = 'using default branch'

  def reapply_pupr_tracking(self, policy_info: PolicyInfo) -> None:
    """Hook invoked after local uprev creation to adjust git tracking."""

  @abc.abstractmethod
  def create_local_uprev(self) -> list[repo_api.ProjectInfo] | None:
    """Create and commit uprevs on the local filesystem."""


class PackageUprevHandler(UprevTargetHandler):
  """Handler for package (ebuild) uprevs."""

  def validate_properties(self) -> None:
    if not self.properties.packages:
      raise recipe_api.StepFailure(
          'must set packages to uprev for a package uprevver')

  def get_default_topic(self) -> str:
    return self.m.naming.get_package_title(self.properties.packages[0])

  def create_local_uprev(self) -> list[repo_api.ProjectInfo] | None:
    target_package_versions = [
        packages_pb2.UprevVersionedPackageRequest.GitRef(
            repository=urllib.parse.urlparse(trigger.gitiles.repo).path,
            ref=trigger.gitiles.ref,
            revision=(self.run.target_version_from_gitiles or
                      trigger.gitiles.revision),
        ) for trigger in self.run.triggers
    ]
    return self.m.pupr_local_uprev.uprev_packages(target_package_versions,
                                                  self.run.topic)


class SdkUprevHandler(UprevTargetHandler):
  """Handler for ChromiumOS SDK uprevs."""

  def validate_properties(self) -> None:
    pass

  def get_default_topic(self) -> str:
    return 'cros_sdk'

  def checkout_default_branch(self, pres: StepPresentation) -> None:
    # b/372434018: The source tree here should be identical to the SDK
    # builder's, unless policy overrides that. The SDK builder's uprevs
    # use source tree state for dependency invalidation through packages
    # like virtual/rust.
    #
    # The SDK builder uses the same mechanism as the CQ for passing source
    # state around.
    self.m.cros_source.sync_checkout(self.m.src_state.gitiles_commit)

  def create_local_uprev(self) -> list[repo_api.ProjectInfo] | None:
    return self.m.pupr_local_uprev.uprev_sdk(self.run.topic)


class VersionFileUprevHandler(UprevTargetHandler):
  """Handler for version file uprevs."""

  def validate_properties(self) -> None:
    if not self.properties.version_files:
      raise recipe_api.StepFailure(
          'must set version_files to uprev for a version file uprevver')

  def get_default_topic(self) -> str:
    return self.m.path.basename(
        self.properties.version_files[0]).lower().replace('_', '-')

  def get_policy_repo_url(self, default_url: str) -> str:
    for v in self.properties.version_files:
      if v.startswith('chrome/') or v.startswith('chromium/'):
        return 'https://chromium.googlesource.com/chromium/src.git'
    return default_url  # pragma: nocover

  def checkout_branch(self, policy_info: PolicyInfo) -> None:
    needs_cros_checkout = True
    if self.properties.version_files:
      needs_cros_checkout = False
      processed_non_repo_dirs = set()
      with self.m.context(cwd=self.m.cros_source.workspace_path):
        for v in self.properties.version_files:
          if self.m.repo.project_exists(str(self.m.path.start_dir / v)):
            needs_cros_checkout = True  # pragma: nocover
          else:
            v_dir = self.m.path.dirname(self.m.path.start_dir / v)
            with self.m.context(cwd=v_dir):
              git_root = self.m.step(
                  f'get git root for {v}',
                  ['git', 'rev-parse', '--show-toplevel'],
                  stdout=self.m.raw_io.output_text(), step_test_data=lambda:
                  self.m.raw_io.test_api.stream_output_text(
                      str(self.m.path.start_dir / 'chrome' / 'src')
                  )).stdout.strip()
              if git_root not in processed_non_repo_dirs:
                target_ref = policy_info.reference.ref.replace(
                    'refs/heads/', 'refs/remotes/origin/')
                target_ref = target_ref.replace('refs/branch-heads/',
                                                'refs/remotes/branch-heads/')
                self.m.git.fetch(
                    remote='origin',
                    refs=[f'{policy_info.reference.ref}:{target_ref}'])
                self.m.git.checkout(commit='FETCH_HEAD',
                                    branch=policy_info.branch)
                self.m.step(f'set upstream remote for {policy_info.branch}', [
                    'git', 'config', f'branch.{policy_info.branch}.remote',
                    'origin'
                ])
                self.m.step(f'set upstream merge for {policy_info.branch}', [
                    'git', 'config', f'branch.{policy_info.branch}.merge',
                    policy_info.reference.ref
                ])
                processed_non_repo_dirs.add(git_root)
    if needs_cros_checkout:  # pragma: nocover
      self.m.cros_source.checkout_branch(self.m.src_state.internal_manifest.url,
                                         policy_info.branch)

  # TODO(b/493779542): Deduplicate non-repo git root resolution and upstream
  # tracking logic between checkout_branch and reapply_pupr_tracking.
  def reapply_pupr_tracking(self, policy_info: PolicyInfo) -> None:
    if not (self.properties.version_files and policy_info.branch):
      return

    processed_non_repo_dirs = set()
    with self.m.context(cwd=self.m.cros_source.workspace_path):
      for v in self.properties.version_files:
        if not self.m.repo.project_exists(str(self.m.path.start_dir / v)):
          v_dir = self.m.path.dirname(self.m.path.start_dir / v)
          with self.m.context(cwd=v_dir):
            git_root = self.m.step(
                f'get git root for {v}',
                ['git', 'rev-parse', '--show-toplevel'],
                stdout=self.m.raw_io.output_text(), step_test_data=lambda: self.
                m.raw_io.test_api.stream_output_text(
                    str(self.m.path.start_dir / 'chrome' / 'src')
                )).stdout.strip()
            if git_root not in processed_non_repo_dirs:
              self.m.step(f'set upstream remote for pupr in {v}',
                          ['git', 'config', 'branch.pupr.remote', 'origin'])
              self.m.step(f'set upstream merge for pupr in {v}', [
                  'git', 'config', 'branch.pupr.merge',
                  policy_info.reference.ref
              ])
              processed_non_repo_dirs.add(git_root)

  def create_local_uprev(self) -> list[repo_api.ProjectInfo] | None:
    target_version_file_versions = [
        packages_pb2.UprevVersionFileRequest.GitRef(
            repository=urllib.parse.urlparse(trigger.gitiles.repo).path,
            ref=trigger.gitiles.ref,
            revision=(self.run.target_version_from_gitiles or
                      trigger.gitiles.revision),
        ) for trigger in self.run.triggers
    ]
    return self.m.pupr_local_uprev.uprev_version_files(
        target_version_file_versions, self.run.topic)


_TARGET_HANDLERS: dict[generator_pb2.UprevTargetKind,
                       type[UprevTargetHandler]] = {
                           generator_pb2.UprevTargetKind.PACKAGE:
                               PackageUprevHandler,
                           generator_pb2.UprevTargetKind.SDK:
                               SdkUprevHandler,
                           generator_pb2.UprevTargetKind.VERSION_FILE:
                               VersionFileUprevHandler,
                       }


class GeneratorRun:
  """A single run of a Generator builder."""

  def __init__(
      self,
      api: recipe_api.RecipeApi,
      properties: generator_pb2.GeneratorProperties,
  ) -> None:
    """Initialize the builder."""
    self.m = api
    self.properties = properties

    self.workspace_path: config_types.Path | None = None
    self._policy: generator_pb2.BranchPolicy | None = None
    self._modified_projects: list[repo_api.ProjectInfo] | None = None
    self._topic: str | None = None

    # If we see gitiles_info populated in the recipe properties, we will be
    # performing a fetch from the Gitiles API for the package's target uprev
    # version. This information will be used in branch determination and sent to
    # the uprev handler.
    self.target_version_from_gitiles = None

    handler_cls = _TARGET_HANDLERS.get(self.properties.uprev_target_kind)
    if not handler_cls:
      raise recipe_api.StepFailure(
          f'Unsupported uprev_target_kind: {self.properties.uprev_target_kind}')
    self.target_handler = handler_cls(self)

  @property
  def triggers(self) -> list[triggers_pb2.Trigger]:
    """Get this run's triggers."""
    return self.properties.triggers or self.m.scheduler.triggers

  @property
  def retry_only_run(self) -> bool:
    """Check whether this is a retry-only run."""
    return self._has_cron_trigger

  @property
  def policy(self) -> generator_pb2.BranchPolicy:
    """Get the branch policy that applies to this build. See generator.proto."""
    assert self._policy is not None
    return self._policy

  def set_policy(self, policy: generator_pb2.BranchPolicy) -> None:
    """Set the policy for this build, and report it as a step."""
    self.m.easy.set_properties_step(policy=json_format.MessageToDict(policy))
    self._policy = policy

  @property
  def topic(self) -> str:
    """Get the topic to use for all generated CLs."""
    if self._topic:
      return self._topic
    if self.properties.topic:
      return self.properties.topic
    return self.target_handler.get_default_topic()

  @property
  def _repo_projects(self) -> list[repo_api.ProjectInfo]:
    """Return all repo projects with code that this PUpr uprevs."""
    assert self._modified_projects is not None
    return self._modified_projects


  @contextlib.contextmanager
  def _workspace_context(self) -> Generator[None, None, None]:
    """Manage the lifecycle of workspace mounts, caches, and source checkouts."""
    chrome_future = None
    if self.properties.checkout_chrome:
      chrome_future = self.m.futures.spawn(self._checkout_chrome)

    with self.m.cros_source.checkout_overlays_context(
    ), self.m.cros_sdk.cleanup_context():
      self.m.cros_source.ensure_synced_cache(manifest_branch_override='main')

      if chrome_future:
        chrome_root = chrome_future.result()
        self.m.cros_sdk.set_chrome_root(chrome_root)

      yield

  def _get_commit_footer(self, limit_exceeded: bool) -> str:
    """Assemble the commit footer based on rate limits."""
    footer = self.properties.additional_commit_footer.strip()
    if not limit_exceeded and self.properties.non_wip_additional_commit_footer:
      non_wip_footer = (
          self.properties.non_wip_additional_commit_footer.strip())
      footer = f'{footer}\n{non_wip_footer}' if footer else non_wip_footer
    return footer

  def _set_local_uprev_generator_attributes(self, limit_exceeded: bool) -> None:
    """Set generator attributes on the pupr_local_uprev module."""
    self.m.pupr_local_uprev.set_generator_config(
        pupr_local_uprev_api.LocalUprevConfig(
            additional_commit_message=self.properties.additional_commit_message,
            additional_commit_footer=self._get_commit_footer(limit_exceeded),
            allow_partial_uprev=self.properties.allow_partial_uprev,
            build_targets=tuple(self.properties.build_targets),
            packages=tuple(self.properties.packages),
            uprev_target_kind=self.properties.uprev_target_kind,
            version_files=tuple(self.properties.version_files),
        ))

  def _run_creation(
      self,
      policy_info: PolicyInfo,
      open_patch_sets: list[PatchSet],
      limit_exceeded: bool,
      running_count: int,
  ) -> Result:
    """Execute uprev creation and upload new CLs."""
    res = Result()
    self._modified_projects = self.create_local_uprev()
    if self._modified_projects is None:
      res.no_action_reason = 'no modified projects'
      return res
    self.target_handler.reapply_pupr_tracking(policy_info)

    open_changes = [ps.to_gerrit_change_proto() for ps in open_patch_sets]
    res.record(
        self.m.pupr_gerrit_interface.create_uprev_cls(
            self._repo_projects,
            open_changes,
            self.policy,
            self.topic,
            limit_exceeded=limit_exceeded,
            running_count=running_count,
        ))
    return res

  def _run_retry(
      self,
      policy_info: PolicyInfo,
      open_patch_sets: list[PatchSet],
      most_recent_uprev: PatchSet | None,
  ) -> Result:
    """Execute retry policy on existing open CLs."""
    res = Result()
    local_rebase_target = res.record(
        self.m.pupr_gerrit_interface.apply_retry_policy_remote(
            open_patch_sets,
            most_recent_uprev,
            self.policy,
            self.retry_only_run,
        ))
    if not local_rebase_target:
      return res

    with self._workspace_context():
      self.checkout_branch(policy_info)
      res.record(
          self.m.pupr_gerrit_interface.rebase_and_retry(
              open_patch_sets,
              local_rebase_target,
              self.policy,
              self.topic,
              self.retry_only_run,
          ))
    return res

  def run(self) -> tuple[int, str]:
    """Run the Generator."""
    self.m.cros_source.configure_builder(self.m.src_state.gitiles_commit,
                                         self.m.src_state.gerrit_changes)
    self.workspace_path = self.m.cros_source.workspace_path

    self._validate_properties()
    self._validate_triggers()
    self.m.pupr_gerrit_interface.set_generator_config(
        pupr_gerrit_interface_api.GerritInterfaceConfig(
            rebase_before_retry=self.properties.rebase_before_retry))

    result = Result()

    if self.retry_only_run:
      policy_info = self._select_policy_for_retry()
      if not policy_info:
        result.no_action_reason = 'no matching policy for retry'
        return result.evaluate(is_retry_only=self.retry_only_run)
      policy_ref = (
          policy_info.reference.ref
          if policy_info.reference else 'refs/heads/main')
      assert policy_ref == self.properties.retry_ref.ref, (
          f'policy reference {policy_ref!r} does not match retry_ref '
          f'{self.properties.retry_ref.ref!r}')
    else:
      policy_info = self.select_policy()

    self.set_policy(policy_info.policy)
    if self.policy.ignore:
      self.m.step.empty('policy set to ignore')
      result.no_action_reason = 'ignore by policy'
      return result.evaluate(is_retry_only=self.retry_only_run)

    branch = policy_info.target_branch
    if self.retry_only_run:
      self.m.pupr_gerrit_interface.apply_automations(self.policy, self.topic,
                                                     branch=branch)
    open_changes = self.m.pupr_gerrit_interface.find_open_uprev_cls(
        self.topic, branch=branch)
    open_patch_sets = self.m.pupr_gerrit_interface.fetch_open_patch_sets(
        open_changes)
    most_recent_uprev = (
        self.m.pupr_gerrit_interface.find_most_recently_merged_uprev(
            self.topic, branch=branch) if open_patch_sets else None)
    open_patch_sets = result.record(
        self.m.pupr_gerrit_interface.handle_outdated_changes(
            open_patch_sets,
            most_recent_uprev,
            self.policy,
            self.retry_only_run,
        ))
    open_patch_sets = result.record(
        self.m.pupr_gerrit_interface.handle_repeatedly_failing_changes(
            open_patch_sets, self.policy.max_cq_retry,
            max_cq_retry_action=self.policy.max_cq_retry_action))

    limit_exceeded, running_count = (
        self.m.pupr_gerrit_interface.check_limit_exceeded(
            open_patch_sets, self.policy))

    self._set_local_uprev_generator_attributes(limit_exceeded)

    if self.retry_only_run:
      result.record(
          self._run_retry(policy_info, open_patch_sets, most_recent_uprev))
      return result.evaluate(is_retry_only=self.retry_only_run)

    with self._workspace_context():
      self.checkout_branch(policy_info)

      if self.m.cv.active or self.m.src_state.gerrit_changes:
        self.cherry_pick_gerrit_changes()
        self.prevent_production_changes()

      if self.properties.init_sdk:
        with self.m.context(cwd=self.workspace_path):
          self.m.cros_sdk.create_chroot()

      result.record(
          self._run_creation(policy_info, open_patch_sets, limit_exceeded,
                             running_count))
      return result.evaluate(is_retry_only=self.retry_only_run)

  def create_local_uprev(self) -> list[repo_api.ProjectInfo] | None:
    """Create and commit uprevs on the local filesystem.

    Returns:
      If the uprev is successful, a list of repo projects with code changes.
      Otherwise, None, signifying that the build should terminate immediately.
    """
    return self.target_handler.create_local_uprev()

  def _validate_properties(self) -> None:
    """Ensure the input properties look OK.

    Raises:
      StepFailure: if there are any issues with the input properties.
    """
    with self.m.step.nest('validate properties') as presentation:
      if self.retry_only_run and not self.properties.retry_ref.ref:
        raise recipe_api.StepFailure('must set retry_ref for retry-only run')
      self.target_handler.validate_properties()

      # Retrieve version information from Gitiles API.
      if self.properties.HasField('gitiles_info'):
        if not (self.properties.gitiles_info.host and
                self.properties.gitiles_info.project and
                self.properties.gitiles_info.path):
          raise recipe_api.StepFailure(
              'gitiles fetch requested with no fetch infomation supplied')

      for policy in self.properties.branch_policies:
        if not policy.pattern:
          raise recipe_api.StepFailure('must specify pattern')
        if (not policy.reviewers and not policy.gerrit_flows and
            not policy.gerrit_automations):
          raise recipe_api.StepFailure(
              'need at least one reviewer, flow, or automation')

        for reviewer in policy.reviewers:
          if not reviewer.email:
            raise recipe_api.StepFailure('must set reviewer email')

      presentation.step_text = 'all properties good'

  def _validate_triggers(self) -> None:
    """Check whether the build's triggers are OK.

    Raises:
      StepFailure: If no triggers are found, or if any non-cron, non-gitiles
      triggers are found.
    """
    with self.m.step.nest('validate triggers') as presentation:
      if not self.triggers:
        raise recipe_api.StepFailure('found no triggers')
      if self._has_cron_trigger:
        presentation.step_text = (
            'has cron trigger, running in retry-only mode')
      else:
        for trigger in self.triggers:
          if not trigger.HasField('gitiles'):
            raise recipe_api.StepFailure('found non-gitiles trigger: %r' %
                                         trigger)

        presentation.step_text = f'found {len(self.triggers)} good triggers'
        presentation.logs['list of triggers'] = map(json_format.MessageToJson,
                                                    self.triggers)

  @property
  def _has_cron_trigger(self) -> bool:
    """Check whether any of this build's triggers is a cron trigger."""
    return any(trigger.HasField('cron') for trigger in self.triggers)

  def _checkout_chrome(self) -> config_types.Path:
    chrome_root = self.m.path.start_dir / 'chrome'
    # We perform a custom git checkout here instead of using chrome.sync()
    # because the generator only needs the repository files of chrome/src to
    # modify/read them (e.g., for LKGM version file uprevs) and doesn't build
    # Chrome. Using chrome.sync() is extremely slow (taking 30+ minutes on a
    # smaller infra bot, not a huge builder bot) and unnecessary since it runs
    # gclient sync, which checks out hundreds of dependency repositories (DEPS),
    # runs gclient hooks (downloading toolchains, sysroots, etc.), and copies
    # the git objects from the cache directory to src/.git rather than reusing
    # them via alternates. Instead, we fetch refs into a local git repository
    # utilizing alternates pointing to the persistent git cache, which is
    # extremely fast and avoids copying git objects, downloading DEPS, or
    # running hooks.
    with self.m.step.nest('checkout chrome'):
      # Use a subdirectory inside the persistent chrome_root for the cache
      # to avoid polluting chrome/src with the .gclient file (which would
      # break git cl upload by looking for a nested src/src directory).
      chrome_cache_path = chrome_root / 'cache_tmp'
      self.m.chrome.cache_sync(cache_path=chrome_cache_path, sync=False,
                               step_name='populate chrome cache')

      chrome_src = chrome_root / 'src'
      chrome_cache_objects_dir = chrome_cache_path.joinpath(
          'chrome_cache/chromium.googlesource.com-chromium-src/objects')

      self.m.file.ensure_directory('ensure chrome src', chrome_src)

      with self.m.context(cwd=chrome_src):
        if not self.m.path.exists(chrome_src / '.git'):
          self.m.step('git init', ['git', 'init'])

        self.m.step('git remote add origin', [
            'git', 'remote', 'add', 'origin',
            'https://chromium.googlesource.com/chromium/src.git'
        ], ok_ret=(0, 128))
        self.m.step('git remote set-url origin', [
            'git', 'remote', 'set-url', 'origin',
            'https://chromium.googlesource.com/chromium/src.git'
        ])

        git_objects_info_dir = chrome_src / '.git/objects/info'
        self.m.file.ensure_directory('ensure .git/objects/info',
                                     git_objects_info_dir)
        self.m.file.write_text('create chrome git reference',
                               git_objects_info_dir / 'alternates',
                               str(chrome_cache_objects_dir))

        refspecs = [
            '+refs/heads/*:refs/remotes/origin/*',
            '+refs/tags/*:refs/tags/*',
            '+refs/branch-heads/*:refs/branch-heads/*',
        ]
        self.m.git.fetch(
            remote='https://chromium.googlesource.com/chromium/src.git',
            refs=refspecs)
        self.m.git.checkout('refs/remotes/origin/main', force=True)

    return chrome_root

  def select_policy(self) -> PolicyInfo:
    """Return the trigger policy that applies to this build.

    This will affect which branch the build will use. If the input properties
    specify gitiles_info, then we will determine the branch based on information
    returned by the Gitiles API. Otherwise, use the gitiles.ref seen in the
    trigger.

    As a side-effect, this function will set the instance-level attribute
    self.target_version_from_gitiles to the last version read from Gitiles, if
    any were.

    Raises:
      StepFailure: If more than one applicable trigger is selected.
    """
    with self.m.step.nest('select policy'):
      return self._select_policy_for_triggers(self.triggers)

  def _select_policy_for_retry(self) -> PolicyInfo | None:
    """Return the policy that applies to this retry run.

    Queries open CLs to recover a temporary trigger from the commit message
    (Pupr-Upstream-Versions) or open CL branch, and selects the matching policy.
    Returns None if there are no open CLs.
    """
    with self.m.step.nest('select policy'):
      retry_branch = (
          self.properties.retry_ref.ref.removeprefix('refs/heads/')
          if self.properties.retry_ref.ref else '')
      open_changes = self.m.pupr_gerrit_interface.find_open_uprev_cls(
          self.topic, branch=retry_branch)
      open_patch_sets = self.m.pupr_gerrit_interface.fetch_open_patch_sets(
          open_changes)
      triggers = self._get_temporary_triggers_for_retry(open_patch_sets)
      if triggers is None:
        return None
      return self._select_policy_for_triggers(triggers)

  def _select_policy_for_triggers(
      self,
      triggers: list[triggers_pb2.Trigger],
  ) -> PolicyInfo:
    """Return the policy that applies to the given triggers."""
    policy_infos: list[PolicyInfo] = []
    for trigger in triggers:
      tag = self._get_target_version_for_trigger(trigger)
      policy_info = self._get_policy_info_for_tag(tag)
      if policy_info not in policy_infos:
        policy_infos.append(policy_info)

    # If we match more than one policy with the triggers, that is an error.
    # For Chrome, we are launched with properties.triggers, for exactly one
    # version. See http://shortn/_qWgYUlVY6X in trigger_official_builds().
    if len(policy_infos) != 1:
      raise recipe_api.StepFailure(
          'expected to find 1 applicable policy, got %d: %s' %
          (len(policy_infos), policy_infos))

    chosen_policy = policy_infos[0]
    self.m.easy.set_properties_step(
        chosen_policy_info={
            'policy': json_format.MessageToDict(chosen_policy.policy),
            'branch': chosen_policy.branch,
            'reference': chosen_policy.reference,
        })
    return chosen_policy

  def _get_temporary_triggers_for_retry(
      self,
      open_patch_sets: list[PatchSet],
  ) -> list[triggers_pb2.Trigger] | None:
    """Determine temporary triggers to select policy on a retry run."""
    if not open_patch_sets:
      return None

    sorted_patch_sets = sorted(open_patch_sets, key=lambda ps: ps.created,
                               reverse=True)
    for ps in sorted_patch_sets:
      description = self.m.gerrit.get_change_description(
          ps.to_gerrit_change_proto())
      upstream_versions = self.m.pupr.extract_upstream_git_refs(description)
      if upstream_versions is not None:
        return [
            triggers_pb2.Trigger(
                gitiles=triggers_pb2.GitilesTrigger(
                    ref=v.ref,
                    repo=v.repository,
                    revision=v.revision,
                )) for v in upstream_versions
        ]

    return [
        triggers_pb2.Trigger(
            gitiles=triggers_pb2.GitilesTrigger(
                ref=self.properties.retry_ref.ref))
    ]

  def _get_target_version_for_trigger(self,
                                      trigger: triggers_pb2.Trigger) -> str:
    """Determine the target uprev version relevant to a given trigger.

    Args:
      trigger: The trigger for this build for which to return a target version.

    Returns:
      A target version to try and uprev to, if this trigger is relevant.
    """
    if self.properties.HasField('gitiles_info'):
      gitiles_response = self._read_gitiles(trigger.gitiles.ref)
      if gitiles_response:
        self.target_version_from_gitiles = gitiles_response
        return gitiles_response
    return trigger.gitiles.ref

  def _read_gitiles(self, ref: str) -> str | None:
    """Read a file via the Gitiles API, as specified by properties.gitiles_info.

    Args:
      ref: The ref on which to read the file from gitiles.

    Returns:
      The stripped contents of the file specified by properties.gitiles_info, on
      the ref specified by the `ref` arg.

    Raises:
      AssertionError: If properties.gitiles_info was not set.
    """
    assert self.properties.HasField('gitiles_info')
    return self.m.gitiles.get_file(
        self.properties.gitiles_info.host,
        self.properties.gitiles_info.project,
        self.properties.gitiles_info.path,
        ref=ref,
        test_output_data='MTIzLjQ1Ni43ODkuMAo=',
    ).decode().strip()

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
    repo_url = self.target_handler.get_policy_repo_url(manifest.url)

    for policy in self.properties.branch_policies:
      if re.match(policy.pattern, tag):
        query = re.sub(policy.pattern, policy.repl, tag)
        if not query:
          return PolicyInfo(policy)
        refs = self.m.git.ls_remote([query], repo_url=repo_url)
        if len(refs) == 1:
          ref = refs[0]
          return PolicyInfo(policy, ref.ref.removeprefix('refs/heads/'), ref)
        if refs:
          raise recipe_api.StepFailure(
              'multiple branches matched {}: {}'.format(
                  query, ' '.join(x.ref for x in refs)))
        # If we found no references, this policy does not apply.

    raise recipe_api.StepFailure(
        'No matching policy found for tag {}'.format(tag))

  def checkout_branch(self, policy_info: PolicyInfo) -> None:
    """Check out the appropriate branch based on the selected policy."""
    with self.m.step.nest('checkout branch') as pres:
      if policy_info.branch:
        assert policy_info.reference is not None
        pres.step_text = 'using {} {}'.format(policy_info.branch,
                                              policy_info.reference.hash)
        self.target_handler.checkout_branch(policy_info)
      else:
        self.target_handler.checkout_default_branch(pres)

  def cherry_pick_gerrit_changes(self) -> None:
    """Cherry-pick changes from Gerrit, if needed.

    This is usually applicable when PUpr runs during CQ, or when called via `bb
    add -cl ${GERRIT_CHANGE}`. The latter might also occur as a result of `cros
    try`.

    Use case: Developer is working on the versioned uprev code for a package,
    such as Chrome, and wants to test the changes prior to landing them in
    chromite. While launching a build with the correct policies and triggers is
    difficult in CQ, it is rather straightforward for the dev to manually launch
    the build with "correct" inputs.

    On the other hand, we should not produce production effects with uncommitted
    changes. To prevent that, anytime this function is called,
    self.prevent_production_changes() should also be called.
    """
    if self.m.src_state.gerrit_changes:
      with self.m.step.nest('cherry-pick gerrit changes'), self.m.context(
          cwd=self.m.cros_source.workspace_path):
        self.m.cros_source.apply_gerrit_changes(self.m.src_state.gerrit_changes)

  def prevent_production_changes(self) -> None:
    """Update the selected policy to avoid changing production.

    In particular, we don't want to submit or CQ+2 any CLs, abandon any
    pre-existing CLs, or comment on anything.

    This function should be called if the PUpr build cherry-picks Gerrit
    changes, such as if it runs during CQ.
    """
    with self.m.step.nest('prevent production changes'):
      self.m.easy.set_properties_step(
          original_policy=json_format.MessageToDict(self.policy))

      user = self.m.buildbucket.build.created_by.replace('user:', '', 1)
      self.policy.reviewers.add().email = user

      dangerous_cq_policies = (generator_pb2.FULL_RUN, generator_pb2.SUBMIT)
      if self.policy.existing_cls_policy in dangerous_cq_policies:
        self.policy.existing_cls_policy = generator_pb2.ABANDON
      if self.policy.no_existing_cls_policy in dangerous_cq_policies:
        self.policy.no_existing_cls_policy = generator_pb2.ABANDON

      self.policy.outdated_cls_policy = generator_pb2.OUTDATED_DO_NOTHING
      self.policy.retry_cl_policy = generator_pb2.NO_RETRY
      self._topic = f'testing-{self.topic}'

      self.m.easy.set_properties_step(
          updated_policy=json_format.MessageToDict(self.policy))


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Create test cases for this recipe."""

  def _policy(**kwargs) -> generator_pb2.BranchPolicy:
    """Create a BranchPolicy, with defaults."""
    kwargs.setdefault('pattern', '.*')
    kwargs.setdefault('ignore', False)
    kwargs.setdefault(
        'reviewers',
        [
            generator_pb2.Reviewer(email='evanhernandez@chromium.org'),
            generator_pb2.Reviewer(
                email='chromeos-continuous-integration-team@google.com'),
        ],
    )
    kwargs.setdefault('existing_cls_policy', generator_pb2.DO_NOTHING)
    kwargs.setdefault('no_existing_cls_policy', generator_pb2.DO_NOTHING)
    kwargs.setdefault('outdated_cls_policy', generator_pb2.OUTDATED_DO_NOTHING)
    kwargs.setdefault('retry_cl_policy', generator_pb2.NO_RETRY)
    kwargs.setdefault('max_cq_retry', -1)
    return generator_pb2.BranchPolicy(**kwargs)

  def _props(**kwargs) -> generator_pb2.GeneratorProperties:
    """Create GeneratorProperties, with defaults."""
    kwargs.setdefault('packages', [
        common_pb2.PackageInfo(
            category='chromeos-base',
            package_name='chromite',
        )
    ])
    kwargs.setdefault('uprev_target_kind',
                      generator_pb2.UprevTargetKind.PACKAGE)
    kwargs.setdefault('build_targets',
                      [common_pb2.BuildTarget(name='build_target')])
    kwargs.setdefault('branch_policies', [_policy()])
    kwargs.setdefault('gitiles_info', None)
    return api.properties(generator_pb2.GeneratorProperties(**kwargs))

  chromite_gitiles_trigger = triggers_pb2.Trigger(
      id='123',
      gitiles=triggers_pb2.GitilesTrigger(
          repo='chromiumos/chromite',
          ref=api.src_state.default_ref,
          revision='deadbeef',
      ),
  )

  def _mock_bot_cls(*cl_nums: int):
    ret = None
    for i, n in enumerate(cl_nums, start=1):
      step = api.pupr_gerrit_interface.set_gerrit_fetch_changes_response(
          'update CL labels', [
              bb_common_pb2.GerritChange(
                  host='chromium-review.googlesource.com', change=n,
                  project='project', patchset=1)
          ], iteration=i)
      ret = (ret + step) if ret else step
    return ret

  def _with_infos(name: str, *args, **kwargs) -> recipe_test_api.TestData:
    return api.test(
        name,
        _mock_bot_cls(1, 1),
        api.repo.project_infos_step_data(
            'commit uprev',
            data=[
                {
                    'project': 'overlay'
                },
            ],
            iteration=1,
        ),
        api.repo.project_infos_step_data(
            'commit uprev',
            data=[
                {
                    'project': 'private-overlay',
                    'remote': 'cros-internal'
                },
            ],
            iteration=2,
        ),
        *args,
        **kwargs,
    )

  def _PropertyContains(check, step_odict, key, substr):
    """Post-process check to assert that an output property contains `substr`.

    Args:
      key: The name of the property to check.
      substr: The substring that should be in the property value.

    Usage:
      yield (
          TEST
          + api.post_process(_PropertyContains, 'base_status', 'belong to'))
    """
    build_properties = post_process.GetBuildProperties(step_odict)
    check(substr in str(build_properties[key]))

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
      _props(
          branch_policies=[_policy(existing_cls_policy=generator_pb2.DRY_RUN)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-dry-run-not-approved-policy',
      _props(branch_policies=[
          _policy(existing_cls_policy=generator_pb2.DRY_RUN_NOT_APPROVED)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-full-run-policy',
      _props(
          branch_policies=[_policy(
              existing_cls_policy=generator_pb2.FULL_RUN)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-abandon-policy',
      _props(
          branch_policies=[_policy(existing_cls_policy=generator_pb2.ABANDON)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-abandon-outdated-policy',
      _props(branch_policies=[
          _policy(outdated_cls_policy=generator_pb2.OUTDATED_ABANDON)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-abandon-no-nothing-policy',
      _props(branch_policies=[
          _policy(outdated_cls_policy=generator_pb2.OUTDATED_DO_NOTHING)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-submit-policy',
      _props(branch_policies=[
          _policy(
              no_existing_cls_policy=generator_pb2.SUBMIT,
              existing_cls_policy=generator_pb2.SUBMIT,
          )
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-uprev-comment-outdated-policy',
      _props(branch_policies=[
          _policy(outdated_cls_policy=generator_pb2.OUTDATED_LEAVE_COMMENT)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'with-gerrit-flow',
      _props(
          branch_policies=[
              _policy(
                  reviewers=None,
                  no_existing_cls_policy=generator_pb2.FULL_RUN,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  outdated_cls_policy=generator_pb2.OUTDATED_ABANDON,
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  max_cq_retry=2,
                  gerrit_flows=[
                      gerrit_pb2.Flow(
                          stage_expressions=[
                              gerrit_pb2.FlowStageExpression(
                                  condition='{self} is -label:Commit-Queue',
                                  action=gerrit_pb2.FlowAction(
                                      name='add-reviewer',
                                      parameters=[
                                          'cros-ec-champion@google.com'
                                      ],
                                  ),
                              ),
                          ],
                      ),
                  ],
              )
          ],
      ),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'add gerrit flows'),
      api.post_check(
          post_process.MustRun,
          'add gerrit flows.add gerrit flow to CL 1.create flow on CL 1',
      ),
      api.post_check(
          post_process.LogContains,
          'add gerrit flows.add gerrit flow to CL 1.create flow on CL 1',
          'expressions',
          ['"name": "add-reviewer"'],
      ),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'fail-validate-props-on-gitiles-fetch-info',
      _props(gitiles_info=generator_pb2.GitilesFetchInfo()),
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
      api.properties(uprev_target_kind=generator_pb2.UprevTargetKind.PACKAGE),
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
          triggers_pb2.Trigger(id='456', webui=triggers_pb2.WebUITrigger()),
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
          '.read output file',
          api.file.read_raw(content='{}'),
      ),
  )

  yield api.test(
      'one-change',
      _mock_bot_cls(1),
      _props(
          branch_policies=[_policy(
              existing_cls_policy=generator_pb2.FULL_RUN)]),
      # Only one changed project.
      api.repo.project_infos_step_data(
          'commit uprev',
          data=[{
              'project': 'overlay'
          }],
          iteration=1,
      ),
      api.repo.project_infos_step_data(
          'commit uprev',
          data=[{
              'project': 'overlay'
          }],
          iteration=2,
      ),
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
      'with-gerrit-changes',
      _props(
          branch_policies=[
              _policy(
                  pattern=r'.*\s*',
                  existing_cls_policy=generator_pb2.SUBMIT,
                  no_existing_cls_policy=generator_pb2.FULL_RUN,
              )
          ],
      ),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.test_util.test_build(
          revision=None,
          extra_changes=[
              bb_common_pb2.GerritChange(
                  host='chromium-review.googlesource.com', change=1234)
          ],
          created_by='user:lamontjones@chromium.org',
      ).build,
      api.post_check(post_process.MustRun, 'prevent production changes'),
      api.post_check(_PropertyContains, 'updated_policy',
                     "'existingClsPolicy': 'ABANDON'"),
      api.post_check(_PropertyContains, 'updated_policy',
                     "'noExistingClsPolicy': 'ABANDON'"),
  )

  yield _with_infos(
      'with-gerrit-changes-with-revision-override',
      _props(
          branch_policies=[_policy(pattern=r'.*\s*')],
          gitiles_info=generator_pb2.GitilesFetchInfo(
              host='chromium.googlesource.com',
              project='chrome/src',
              path='foo/bar.txt',
          ),
      ),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'prevent production changes'),
      api.post_check(
          post_process.MustRun,
          'select policy.fetch gitiles file.'
          'curl https://chromium.googlesource.com'
          '/chrome/src/+/refs/heads/main/foo/bar.txt?format=TEXT',
      ),
      api.test_util.test_build(
          revision=None,
          extra_changes=[
              bb_common_pb2.GerritChange(
                  host='chromium-review.googlesource.com', change=1234)
          ],
          created_by='user:lamontjones@chromium.org',
      ).build,
  )

  yield _with_infos(
      'with-gerrit-changes-and-dry-run-policy',
      _props(
          branch_policies=[
              _policy(
                  pattern=r'.*\s*',
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
      ),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.test_util.test_build(
          revision=None,
          extra_changes=[
              bb_common_pb2.GerritChange(
                  host='chromium-review.googlesource.com', change=1234)
          ],
          created_by='user:lamontjones@chromium.org',
      ).build,
      api.post_check(post_process.MustRun, 'prevent production changes'),
      api.post_check(_PropertyContains, 'updated_policy',
                     "'existingClsPolicy': 'DRY_RUN'"),
      api.post_check(_PropertyContains, 'updated_policy',
                     "'noExistingClsPolicy': 'DRY_RUN'"),
  )

  yield _with_infos(
      'cq-active',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.post_check(post_process.MustRun, 'prevent production changes'),
      api.test_util.test_build(revision=None, extra_changes=[],
                               created_by='project:chromiumos').build,
  )

  # Set up for testing chromeos-base/chromeos-chrome trigger filtering.
  package_chrome = common_pb2.PackageInfo(category='chromeos-base',
                                          package_name='chromeos-chrome')
  trigger_prop = json_format.MessageToDict(
      triggers_pb2.Trigger(
          id='123',
          gitiles=triggers_pb2.GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/tags/79.0.3945.20',
              revision='83a1812dddfc24f604d92bf61ad58efe9227a6fc',
          ),
      ))

  trigger_prop2 = json_format.MessageToDict(
      triggers_pb2.Trigger(
          id='456',
          gitiles=triggers_pb2.GitilesTrigger(
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
          packages=[package_chrome],
          branch_policies=[
              _policy(reviewers=[
                  generator_pb2.Reviewer(email='dburger@chromium.org')
              ])
          ],
      ),
      api.properties(triggers=[trigger_prop]),
  )

  branch_policy = _policy(
      pattern='refs/tags/([0-9]*).*',
      repl=r'release-R\1-*.B',
      reviewers=[generator_pb2.Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=generator_pb2.DRY_RUN,
      existing_cls_policy=generator_pb2.DRY_RUN,
      outdated_cls_policy=generator_pb2.OUTDATED_ABANDON,
  )
  no_pattern_policy = _policy(
      pattern='',
      repl=r'release-R\1-*.B',
      reviewers=[generator_pb2.Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=generator_pb2.DRY_RUN,
      existing_cls_policy=generator_pb2.DRY_RUN,
      outdated_cls_policy=generator_pb2.OUTDATED_ABANDON,
  )

  yield _with_infos(
      'branch-policies',
      api.properties(triggers=[trigger_prop]),
      _props(packages=[package_chrome], branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.step_data(
          'select policy.git ls-remote',
          api.raw_io.stream_output_text(
              'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\trefs/heads/release-R79-12345.B\n'
          ),
      ),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(
          post_process.MustRun,
          'checkout branch.checkout branch release-R79-12345.B',
      ),
  )

  yield _with_infos(
      'branch-policies-multiple-triggers',
      api.properties(triggers=[trigger_prop] * 2),
      _props(packages=[package_chrome], branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.step_data(
          'select policy.git ls-remote',
          api.raw_io.stream_output_text(
              'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\trefs/heads/release-R79-12345.B\n'
          ),
      ),
      api.step_data(
          'select policy.git ls-remote (2)',
          api.raw_io.stream_output_text(
              'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\trefs/heads/release-R79-12345.B\n'
          ),
      ),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(
          post_process.MustRun,
          'checkout branch.checkout branch release-R79-12345.B',
      ),
  )

  yield api.test(
      'branch-policies-multiple-trigger-policies',
      api.properties(triggers=[trigger_prop, trigger_prop2]),
      _props(
          packages=[package_chrome],
          branch_policies=[branch_policy, _policy()],
      ),
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
          packages=[package_chrome],
          branch_policies=[
              generator_pb2.BranchPolicy(
                  pattern='.*',
                  repl='',
                  reviewers=[generator_pb2.Reviewer(email='a@example.com')],
              )
          ],
      ),
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
          ])),
      ),
      status='FAILURE',
  )

  yield api.test(
      'version-file-uprev-branch-policy',
      _mock_bot_cls(1),
      api.properties(triggers=[trigger_prop]),
      _props(
          uprev_target_kind=generator_pb2.UprevTargetKind.VERSION_FILE,
          version_files=['chrome/src/chromeos/CHROMEOS_LKGM'],
          branch_policies=[_policy(
              pattern='.*',
              repl='branch-heads/7871',
          )],
      ),
      api.step_data(
          'select policy.git ls-remote',
          stdout=api.raw_io.output_text(
              '7df59670d5e95a464e3f9cecd242586f7d4860ee\trefs/branch-heads/7871\n'
          ),
      ),
      api.step_data(
          'checkout branch.check if project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM exists.repo info',
          api.raw_io.stream_output_text(
              'project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM not found',
              stream='stderr'),
          retcode=1,
      ),
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content='{"responses": [{"version": "16626.0.0-1076201", "modified_files": ["[START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM"]}]}'
          )),
      api.step_data(
          'check if project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM exists.repo info',
          api.raw_io.stream_output_text(
              'project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM not found',
              stream='stderr'),
          retcode=1,
      ),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(
          post_process.MustRun,
          'checkout branch.git checkout',
      ),
      api.post_check(
          post_process.MustRun,
          'set upstream remote for pupr in chrome/src/chromeos/CHROMEOS_LKGM',
      ),
      api.post_check(
          post_process.MustRun,
          'set upstream merge for pupr in chrome/src/chromeos/CHROMEOS_LKGM',
      ),
      api.post_check(
          post_process.MustRun,
          'generate CLs.create gerrit change for [START_DIR]/chrome/src.git_cl upload',
      ),
  )

  yield _with_infos(
      'multiple-packages',
      _mock_bot_cls(1, 1, 1, 1),
      api.properties(triggers=[trigger_prop]),
      _props(
          packages=[
              package_chrome,
              common_pb2.PackageInfo(category='chromeos-base',
                                     package_name='chromeos-lacros'),
          ],
          topic='chromeos-base/new-topic-name',
      ),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-chrome'),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-lacros'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in overlay.write commit message',
          [
              '.*',
              '.*',
              '.*',
              '.*',
              '.*',
              '.*',
              r'(.|\n)*Pupr-Upstream-Versions: \[\{\"ref\": \"refs/tags/79.0.3945.20\", \"repository\": \"/chromium/src\", \"revision\": \"83a1812dddfc24f604d92bf61ad58efe9227a6fc\"\}\](.|\n)*',
              '.*',
          ],
      ),
      api.post_check(
          post_process.StepCommandContains,
          'generate CLs.create gerrit change for src/overlay.git_cl upload',
          ['--topic', 'chromeos-base/new-topic-name'],
      ),
  )

  changes = [
      bb_common_pb2.GerritChange(change=1,
                                 host='chromium-review.googlesource.com'),
      bb_common_pb2.GerritChange(change=2,
                                 host='chromium-review.googlesource.com'),
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

  retry_ref = generator_pb2.RetryRef(
      ref='refs/heads/main',
  )

  revision = '83a1812dddfc24f604d92bf61ad58efe9227a6fc'
  change_description = (
      'a quick description\n\n'
      'Change-Id: deadbeef\n\n'
      f'Pupr-Upstream-Versions: [{{"ref": "refs/heads/main", "repository": "https://chromium.googlesource.com/chromium/src", "revision": "{revision}"}}]'
  )
  value_dict_desc = {
      1: {
          'message': change_description,
      },
      2: {
          'message': change_description,
      },
  }
  value_dict = {
      1: {
          'change_id':
              1,
          'created':
              '2020-10-22 18:54:00.000000000',
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
                  'tag': 'autogenerated:cv:full-run:1000000001',
              },
              {
                  'message':
                      'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
                  'date':
                      '2020-10-25T18:54:00Z',
                  'tag':
                      'autogenerated:cv:full-run:1000000002',
              },
          ],
      },
      2: {
          'change_id': 2,
          'created': '2020-10-23 18:54:00.000000000',
      },
  }

  value_dict_wip = dict(value_dict)
  value_dict_wip[1] = dict(value_dict[1])
  value_dict_wip[1]['status'] = 'NEW'
  value_dict_wip[1]['hashtags'] = ['pupr-retry-pinned']
  value_dict_wip[1]['work_in_progress'] = True

  value_dict_passed_dry_run = dict(value_dict)
  value_dict_passed_dry_run[2] = dict(value_dict[2])
  value_dict_passed_dry_run[2]['messages'] = [
      {
          'message': 'Patch Set 3:\n\nThis CL has passed the run',
          'date': '2020-10-25T18:54:00Z',
          'tag': 'autogenerated:cv:dry-run:1000000002',
      },
  ]

  yield _with_infos(
      'no-most-recent-merged-cl',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chrome-internal host (within 30 days)',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.post_check(post_process.DoesNotRun, 'outdated CLs'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-retry-policy',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy',
          changes,
          value_dict,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          value_dict,
      ),
  )

  yield api.test(
      'with-retry-policy-but-no-open-changes',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          [],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.post_check(
          post_process.DoesNotRun,
          'find open uprev CLs',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-retry-policy-but-retries-frozen',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          [gerrit_changes_json[0]],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 1 description',
          changes[:1],
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          [gerrit_changes_json[0]],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes[:1],
          {
              1: {
                  'change_id': 777,
                  'created': '2020-10-22 18:54:00.000000000',
                  'hashtags': [pupr_api.HASHTAG_FREEZE_RETRIES],
              }
          },
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
      ),
      api.post_check(
          post_process.DoesNotRunRE,
          r'apply retry policy RETRY_LATEST_OR_LATEST_PINNED\.retry CL .*',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-retry-policy-but-no-retry-cl-identified',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          [gerrit_changes_json[1]],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes[1:2],
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          [gerrit_changes_json[1]],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes[1:2],
          value_dict,
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
      ),
      api.post_check(
          post_process.DoesNotRun,
          r'apply retry policy RETRY_LATEST_OR_LATEST_PINNED\.retry CL .*',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-triggers',
      _props(),
      api.scheduler(triggers=[]),
      api.git.diff_check(True),
      status='FAILURE',
  )

  yield api.test(
      'cron-trigger',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy',
          changes,
          value_dict,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          value_dict,
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
      ),
      api.post_check(
          post_process.DoesNotRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.commit uprev.commit in overlay.write commit message',
      ),
  )

  yield _with_infos(
      'non-wip-additional-footer',
      _mock_bot_cls(1, 1, 1, 1),
      api.properties(triggers=[trigger_prop]),
      _props(
          packages=[
              package_chrome,
              common_pb2.PackageInfo(category='chromeos-base',
                                     package_name='chromeos-lacros'),
          ],
          non_wip_additional_commit_footer='Test-Footer: foo',
      ),
      api.git.diff_check(True),
  )

  yield _with_infos(
      'non-wip-additional-footer-throttled',
      _mock_bot_cls(1, 1, 1, 1),
      api.properties(triggers=[trigger_prop]),
      _props(
          packages=[
              package_chrome,
              common_pb2.PackageInfo(category='chromeos-base',
                                     package_name='chromeos-lacros'),
          ],
          non_wip_additional_commit_footer='Test-Footer: foo',
          branch_policies=[
              _policy(
                  max_concurrent_cq_runs=1,
                  existing_cls_policy=generator_pb2.FULL_RUN,
                  no_existing_cls_policy=generator_pb2.FULL_RUN,
              )
          ],
      ),
      api.git.diff_check(True),
      api.git.diff_check(True),
      api.cros_build_api.set_upreved_ebuilds(
          ['src/overlay/foo.ebuild', 'src/private-overlay/bar.ebuild']),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          {
              1: {
                  'change_id':
                      1,
                  'created':
                      '2020-10-22 18:54:00.000000000',
                  'messages': [{
                      'message': 'Patch Set 3:\n\nCV is trying the patch...',
                      'date': '2020-10-27T18:54:00Z',
                      'tag': 'autogenerated:cv:full-run:1000000001',
                  },],
              },
          },
      ),
      api.repo.project_infos_step_data(
          'commit uprev',
          data=[
              {
                  'project': 'overlay'
              },
          ],
          iteration=1,
      ),
      api.repo.project_infos_step_data(
          'commit uprev',
          data=[
              {
                  'project': 'private-overlay',
                  'remote': 'cros-internal'
              },
          ],
          iteration=2,
      ),
  )

  yield api.test(
      'cron-trigger-rebase',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
          rebase_before_retry=True,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy',
          changes,
          value_dict,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          value_dict,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'rebase CL 1.get CL 1 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.test gerrit mergeable',
          'chromium-review.googlesource.com',
          1,
          'current',
          False,
      ),
      api.git_footers.simulated_get_footers(['deadbeef'],
                                            parent_step_name='rebase CL 1'),
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']),
      api.post_check(
          post_process.StepSuccess,
          'rebase CL 1',
      ),
      # Commit message should contain the same version label as the original.
      # The change should be uploaded as a new patch set for the same Change-Id.
      api.post_check(
          post_process.StepCommandRE,
          'rebase CL 1.commit uprev.commit in overlay.write commit message',
          [
              '.*',
              '.*',
              '.*',
              '.*',
              '.*',
              '.*',
              r'(.|\n)*' + pupr_api.UPREV_VERSION_LABEL + '.*' + revision +
              r'(.|\n)*Change-Id: deadbeef(.|\n)*',
              '.*',
          ],
      ),
      api.post_check(
          post_process.MustRunRE,
          r'.*upload patch set for Change-Id 1\.git_cl upload',
      ),
  )

  yield api.test(
      'cron-trigger-rebase-wip',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
          rebase_before_retry=True,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy',
          changes,
          value_dict_wip,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          value_dict_wip,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'rebase CL 1.get CL 1 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.test gerrit mergeable',
          'chromium-review.googlesource.com',
          1,
          'current',
          True,
      ),
      api.git_footers.simulated_get_footers(['deadbeef'],
                                            parent_step_name='rebase CL 1'),
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']),
      api.repo.project_infos_step_data(
          'rebase CL 1.commit uprev',
          data=[{
              'project': 'overlay',
              'path': 'src/third_party/chromiumos-overlay',
          }],
      ),
      api.repo.project_infos_step_data(
          'upload patch set for Change-Id 1',
          data=[{
              'project': 'chromium/src',
              'path': 'src/chromium',
          }],
      ),
      api.post_check(
          post_process.DoesNotRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.mark CL 1 ready for review',
      ),
  )

  yield api.test(
      'cron-trigger-wip-no-rebase',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
          rebase_before_retry=False,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy',
          changes,
          value_dict_wip,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          value_dict_wip,
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.mark CL 1 ready for review',
      ),
  )

  yield api.test(
      'cron-trigger-discard-before-passed-dry-run',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.FULL_RUN,
                  outdated_cls_policy=generator_pb2.OUTDATED_ABANDON,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy',
          changes,
          value_dict_passed_dry_run,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 2 description',
          changes,
          value_dict_desc,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes,
          value_dict_passed_dry_run,
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.abandon CLs before passed CQ+1 CL.abandon CL 1',
      ),
  )

  merged_value_dict = {
      1: {
          'change_id': 1,
          'status': 'MERGED',
          'submitted': '2020-10-25 18:54:00.000000000',
          'created': '2020-10-22 18:54:00.000000000',
      },
      2: {
          'change_id': 2,
          'status': 'MERGED',
          'submitted': '2020-10-25 18:54:00.000000000',
          'created': '2020-10-23 18:54:00.000000000',
      },
  }

  yield api.test(
      'no-merged-changes-warning',
      _mock_bot_cls(1, 1),
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chrome-internal host (within 30 days)',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          changes,
          merged_value_dict,
      ),
      api.post_check(
          post_process.StepWarning,
          'examine outdated CLs.merged CLs from chrome-internal host (within 30 days)',
      ),
  )

  yield api.test(
      'sdk-uprev',
      _mock_bot_cls(1, 1),
      _props(uprev_target_kind=generator_pb2.UprevTargetKind.SDK),
      api.properties(
          **{
              '$chromeos/pupr_local_uprev':
                  pupr_local_uprev_pb2.PuprLocalUprevProperties(
                      sdk_uprev_spec=pupr_local_uprev_pb2.SdkUprevSpec(
                          sdk_version='2023.03.14.159265',
                          toolchain_template='2023/03/%(target)s-2023.03.14.159265.tar.xz',
                      ),
                  ),
          }),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
  )

  yield api.test(
      'sync-chrome',
      _props(checkout_chrome=True),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.MustRun, 'checkout chrome'),
      api.post_check(post_process.MustRun,
                     'checkout chrome.populate chrome cache'),
      api.post_check(post_process.MustRun, 'checkout chrome.git fetch'),
      api.post_check(post_process.MustRun, 'checkout chrome.git checkout'),
  )

  yield api.test(
      'version-file-uprev',
      _mock_bot_cls(1),
      _props(
          uprev_target_kind=generator_pb2.UprevTargetKind.VERSION_FILE,
          version_files=['chrome/src/chromeos/CHROMEOS_LKGM'],
          packages=[],
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(
              gitiles=triggers_pb2.GitilesTrigger(
                  repo='https://chrome-internal.googlesource.com/chromeos/manifest-internal',
                  ref='refs/heads/snapshot',
                  revision='50a00e4166dc7fca08f026792b8d53f751d536b7',
              ),
          ),
      ]),
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content='{"responses": [{"version": "16626.0.0-1076201", "modified_files": ["[START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM"]}]}'
          )),
      api.git.diff_check(True),
      api.post_check(
          post_process.MustRun,
          'generate CLs.create gerrit change for [START_DIR]/chrome/src.git_cl upload',
      ),
  )

  yield api.test(
      'version-file-uprev-no-file',
      _props(
          uprev_target_kind=generator_pb2.UprevTargetKind.VERSION_FILE,
          packages=[],
      ),
      status='FAILURE',
  )

  yield api.test(
      'unsupported-uprev-target-kind',
      _props(
          uprev_target_kind=generator_pb2.UprevTargetKind
          .UPREV_TARGET_KIND_UNSPECIFIED,
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'cannot-verified-minus-one-fails-at-end',
      _props(
          branch_policies=[
              _policy(
                  max_cq_retry=1,
                  max_cq_retry_action=generator_pb2
                  .MAX_CQ_RETRY_ACTION_VERIFIED_MINUS_ONE,
              ),
          ],
          retry_ref=generator_pb2.RetryRef(ref='refs/heads/main'),
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(
              cron=triggers_pb2.CronTrigger(generation=1),
          ),
      ]),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          [{
              '_number': 1235,
              'project': 'chromium/src',
              'branch': 'main',
              'change_id': 'Ideadbeef',
          }],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          [
              bb_common_pb2.GerritChange(
                  host='chromium-review.googlesource.com', change=1235,
                  project='chromium/src', patchset=1)
          ],
          {
              1235: {
                  'patch_set': 1,
                  'files': {
                      'a/b/d/test.txt': {}
                  },
                  'branch': 'main',
                  'hashtags': [],
                  'created': '2023-01-09 13:11:20.000000000',
                  'messages': [{
                      'date':
                          1234 + i,
                      'tag':
                          'autogenerated:cq:full-run:1235',
                      'message':
                          'Patch Set 1:  This CL has failed the run. Reason:'
                  } for i in range(3)],
                  'message': 'Change commit message',
                  'labels': {
                      'Bot-Commit': {
                          'value': 1
                      },
                      'Commit-Queue': {
                          'value': 0
                      },
                  },
              },
          },
      ),
      api.post_check(
          post_process.MustRun,
          'set Verified-1 on unpinned CLs repeatedly failing CQ',
      ),
      api.post_check(
          post_process.MustRun,
          'set Verified-1 on unpinned CLs repeatedly failing CQ.add comment on CL 1235',
      ),
      api.post_check(
          post_process.MustRun,
          'set Verified-1 on unpinned CLs repeatedly failing CQ.set labels on CL 1235',
      ),
      api.post_check(
          post_process.LogEquals,
          'set Verified-1 on unpinned CLs repeatedly failing CQ.set labels on CL 1235',
          'labels', '{"Bot-Commit": 0}'),
      api.post_check(
          post_process.MustRun,
          'set Verified-1 on unpinned CLs repeatedly failing CQ.add hashtags on CL 1235',
      ),
      status='FAILURE',
  )

  yield api.test(
      'retry-no-retry-ref-property',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r'must set retry_ref for retry-only run',
      ),
      status='FAILURE',
  )

  value_dict_unknown_tag = {
      1: {
          'change_id':
              1,
          'created':
              '2020-10-22 18:54:00.000000000',
          'branch':
              'release-R79-12345.B',
          'message': (
              'a quick description\n\nChange-Id: deadbeef\n\n'
              'Pupr-Upstream-Versions: [{"ref": "refs/tags/unknown-tag", "repository": "/chromium/src", "revision": "deadbeef"}]'
          ),
      },
  }

  yield api.test(
      'retry-upstream-ref-mismatch',
      _props(
          packages=[package_chrome],
          branch_policies=[
              _policy(
                  pattern=r'refs/tags/79\..*',
                  repl='release-R79-12345.B',
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=generator_pb2.RetryRef(
              ref='refs/heads/release-R79-12345.B'),
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 1 description',
          changes[:1],
          value_dict_unknown_tag,
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json[:1],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      status='FAILURE',
  )

  value_dict_version_file_desc = {
      1: {
          'message': (
              'a quick description\n\nChange-Id: deadbeef\n\n'
              'Pupr-Upstream-Versions: [{"ref": "refs/heads/release-R79-12345.B-snapshot", "repository": "/chromiumos/manifest-internal", "revision": "deadbeef"}]'
          ),
      },
  }

  value_dict_version_file = {
      1: {
          'change_id': 1,
          'created': '2020-10-22 18:54:00.000000000',
      },
  }

  yield api.test(
      'retry-version-file-release-branch',
      _props(
          uprev_target_kind=generator_pb2.UprevTargetKind.VERSION_FILE,
          version_files=['chrome/src/chromeos/CHROMEOS_LKGM'],
          packages=[],
          branch_policies=[
              _policy(
                  pattern=r'refs/heads/release-R79-12345\.B-snapshot',
                  repl='branch-heads/3945',
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=generator_pb2.RetryRef(ref='refs/branch-heads/3945'),
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.step_data(
          'select policy.git ls-remote',
          api.raw_io.stream_output_text(
              'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\trefs/branch-heads/3945\n'
          ),
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 1 description',
          changes[:1],
          value_dict_version_file_desc,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes[:1],
          value_dict_version_file,
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json[:1],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json[:1],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
  )

  value_dict_no_footer_desc = {
      1: {
          'message': 'a quick description\n\nChange-Id: deadbeef\n',
      },
  }

  value_dict_no_footer = {
      1: {
          'change_id': 1,
          'created': '2020-10-22 18:54:00.000000000',
      },
  }

  yield api.test(
      'retry-no-footer-fallback',
      _props(
          branch_policies=[
              _policy(
                  retry_cl_policy=generator_pb2.RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=generator_pb2.DRY_RUN,
                  no_existing_cls_policy=generator_pb2.DRY_RUN,
              )
          ],
          retry_ref=retry_ref,
      ),
      api.scheduler(triggers=[
          triggers_pb2.Trigger(cron=triggers_pb2.CronTrigger(generation=-1))
      ]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'select policy.get CL 1 description',
          changes[:1],
          value_dict_no_footer_desc,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          None,
          changes[:1],
          value_dict_no_footer,
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json[:1],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'select policy.find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json[:1],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chrome-internal host',
          [],
          'https://chrome-internal-review.googlesource.com',
      ),
      api.post_process(post_process.DropExpectation),
  )
