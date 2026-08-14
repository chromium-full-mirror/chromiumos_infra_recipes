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

import contextlib
import dataclasses
import functools
import re
from typing import Generator, List, Optional
import urllib

from google.protobuf import json_format
from PB.chromite.api import packages as packages_pb2
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.pupr_local_uprev import (pupr_local_uprev as
                                                         pupr_local_uprev_pb2)
from PB.recipes.chromeos import generator as generator_pb2
from recipe_engine import config_types
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from RECIPE_MODULES.chromeos.git import api as git_api
from RECIPE_MODULES.chromeos.pupr import api as pupr_api
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
    'gitiles',
    'naming',
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
  summary = GeneratorRun(api, properties).run()
  return result_pb2.RawResult(status=bb_common_pb2.SUCCESS,
                              summary_markdown=summary)


@dataclasses.dataclass
class PolicyInfo:
  policy: generator_pb2.BranchPolicy
  branch: str = ''
  reference: Optional[git_api.Reference] = None


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

    self.workspace_path: Optional[config_types.Path] = None
    self._policy: Optional[generator_pb2.BranchPolicy] = None
    self._modified_projects: Optional[List[repo_api.ProjectInfo]] = None

    # If we see gitiles_info populated in the recipe properties, we will be
    # performing a fetch from the Gitiles API for the package's target uprev
    # version. This information will be used in branch determination and sent to
    # the uprev handler.
    self.target_version_from_gitiles = None

  @property
  def _is_package_uprevver(self) -> bool:
    """Return whether this generator run is a package uprevver."""
    return (self.properties.uprev_target_kind is
            generator_pb2.UprevTargetKind.PACKAGE)

  @property
  def _is_sdk_uprevver(self) -> bool:
    """Return whether this generator run is an SDK uprevver."""
    return (self.properties.uprev_target_kind is
            generator_pb2.UprevTargetKind.SDK)

  @property
  def is_version_file_uprevver(self) -> bool:
    """Return whether this generator run is a version file uprevver."""
    return (self.properties.uprev_target_kind
            is generator_pb2.UprevTargetKind.VERSION_FILE)

  @functools.cached_property
  def triggers(self) -> List[triggers_pb2.Trigger]:
    """Get this run's triggers, all of which have the gitiles field set."""
    if self._has_cron_trigger:
      return [
          triggers_pb2.Trigger(
              gitiles=triggers_pb2.GitilesTrigger(
                  ref=self.properties.retry_ref.ref))
      ]
    return self._raw_triggers

  @property
  def target_package_versions(
      self,
  ) -> List[packages_pb2.UprevVersionedPackageRequest.GitRef]:
    """Return the package versions to try to uprev to.

    Raises:
      InfraFailure: If this generator does not uprev packages.
    """
    assert self._is_package_uprevver
    return [
        packages_pb2.UprevVersionedPackageRequest.GitRef(
            repository=urllib.parse.urlparse(trigger.gitiles.repo).path,
            ref=trigger.gitiles.ref,
            revision=(self.target_version_from_gitiles or
                      trigger.gitiles.revision),
        ) for trigger in self.triggers
    ]

  @property
  def target_version_file_versions(
      self,
  ) -> List[packages_pb2.UprevVersionFileRequest.GitRef]:
    """Return the version file versions to try to uprev to.

    Raises:
      InfraFailure: If this generator does not uprev version files.
    """
    assert self.is_version_file_uprevver
    return [
        packages_pb2.UprevVersionFileRequest.GitRef(
            repository=urllib.parse.urlparse(trigger.gitiles.repo).path,
            ref=trigger.gitiles.ref,
            revision=(self.target_version_from_gitiles or
                      trigger.gitiles.revision),
        ) for trigger in self.triggers
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
    if self.policy and self.policy.topic:
      return self.policy.topic
    if self.properties.topic:
      return self.properties.topic
    if self._is_package_uprevver:
      return self.cpvs[0]
    if self._is_sdk_uprevver:
      return 'cros_sdk'
    if self.is_version_file_uprevver:
      return self.m.path.basename(
          self.properties.version_files[0]).lower().replace('_', '-')
    raise recipe_api.InfraFailure(
        'Not sure how to generate topic')  # pragma: nocover

  @property
  def _repo_projects(self) -> List[repo_api.ProjectInfo]:
    """Return all repo projects with code that this PUpr uprevs."""
    assert self._modified_projects is not None
    return self._modified_projects

  def make_summary(self, msg: str) -> str:
    if self.retry_only_run:
      return f'[retry-only] {msg}'
    return msg

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

  def _get_target_branch(self, policy_info: PolicyInfo) -> str:
    """Determine the branch to query on Gerrit."""
    if self.retry_only_run:
      ref = self.properties.retry_ref.ref
      return ref[len('refs/heads/'):] if ref.startswith('refs/heads/') else ref
    return policy_info.branch or 'main'

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
    self.m.pupr_local_uprev.set_generator_attributes(
        additional_commit_message=self.properties.additional_commit_message,
        additional_commit_footer=self._get_commit_footer(limit_exceeded),
        allow_partial_uprev=self.properties.allow_partial_uprev,
        build_targets=self.properties.build_targets,
        packages=self.properties.packages,
        uprev_target_kind=self.properties.uprev_target_kind,
        version_files=self.properties.version_files,
    )

  def _run_creation(
      self,
      policy_info: PolicyInfo,
      open_changes: List[common_pb2.GerritChange],
      limit_exceeded: bool,
      running_count: int,
  ) -> str:
    """Execute uprev creation and upload new CLs."""
    self._modified_projects = self.create_local_uprev()
    if self._modified_projects is None:
      return self.make_summary('no modified projects')
    self._reapply_pupr_tracking_for_non_repo_projects(policy_info)

    return self.m.pupr_gerrit_interface.create_uprev_cls(
        self._repo_projects,
        open_changes,
        self.policy,
        self.topic,
        limit_exceeded=limit_exceeded,
        running_count=running_count,
    )

  def _run_retry(
      self,
      open_changes: List[common_pb2.GerritChange],
      most_recent_uprev: Optional[common_pb2.GerritChange],
  ) -> str:
    """Execute retry policy on existing open CLs."""
    self.m.pupr_gerrit_interface.apply_retry_policy(
        open_changes,
        most_recent_uprev,
        self.policy,
        self.topic,
        self.retry_only_run,
    )
    return self.make_summary('success')

  def run(self) -> str:
    """Run the Generator."""
    self.m.cros_source.configure_builder(self.m.src_state.gitiles_commit,
                                         self.m.src_state.gerrit_changes)
    self.workspace_path = self.m.cros_source.workspace_path

    self._validate_properties()
    self._validate_triggers()
    self.m.pupr_gerrit_interface.rebase_before_retry = (
        self.properties.rebase_before_retry)

    with self._workspace_context():
      policy_info = self.select_policy()
      self.set_policy(policy_info.policy)
      if self.policy.ignore:
        self.m.step.empty('policy set to ignore')
        return self.make_summary('ignore by policy')
      self.checkout_branch(policy_info)

      if self.m.cv.active or self.m.src_state.gerrit_changes:
        self.cherry_pick_gerrit_changes()
        self.prevent_production_changes()

      if self.properties.init_sdk:
        with self.m.context(cwd=self.workspace_path):
          self.m.cros_sdk.create_chroot()

      branch = self._get_target_branch(policy_info)
      open_changes = self.m.pupr_gerrit_interface.find_open_uprev_cls(
          self.topic, branch=branch)
      most_recent_uprev = (
          self.m.pupr_gerrit_interface.find_most_recently_merged_uprev(
              self.topic, branch=branch) if open_changes else None)
      open_changes = (
          self.m.pupr_gerrit_interface.handle_outdated_changes(
              open_changes,
              most_recent_uprev,
              self.policy,
              self.retry_only_run,
          ))
      open_changes = (
          self.m.pupr_gerrit_interface.handle_repeatedly_failing_changes(
              open_changes, self.policy.max_cq_retry,
              max_cq_retry_action=self.policy.max_cq_retry_action))

      limit_exceeded, running_count = (
          self.m.pupr_gerrit_interface.check_limit_exceeded(
              open_changes, self.policy))

      self._set_local_uprev_generator_attributes(limit_exceeded)

      if self.retry_only_run:
        # Retry-only runs evaluate retry policies for existing open CLs.
        return self._run_retry(open_changes, most_recent_uprev)

      # A real uprev creation run creates local uprev commits on disk.
      # Retry policy execution is skipped here because applying a local rebase
      # on top of newly created local commits in the same task workspace
      # would cause conflicts. Uprev creation and retry runs are mutually
      # exclusive execution paths.
      return self._run_creation(policy_info, open_changes, limit_exceeded,
                                running_count)

  def create_local_uprev(self) -> Optional[List[repo_api.ProjectInfo]]:
    """Create and commit uprevs on the local filesystem.

    Returns:
      If the uprev is successful, a list of repo projects with code changes.
      Otherwise, None, signifying that the build should terminate immediately.
    """
    if self._is_package_uprevver:
      return self.m.pupr_local_uprev.uprev_packages(
          self.target_package_versions, self.topic)
    if self._is_sdk_uprevver:
      return self.m.pupr_local_uprev.uprev_sdk(self.topic)
    if self.is_version_file_uprevver:
      return self.m.pupr_local_uprev.uprev_version_files(
          self.target_version_file_versions, self.topic)
    raise recipe_api.InfraFailure('Not sure how to uprev.')  # pragma: nocover

  def _reapply_pupr_tracking_for_non_repo_projects(
      self, policy_info: PolicyInfo) -> None:
    """Re-apply git branch tracking information for the 'pupr' branch.

    pupr_local_uprev checks out a new branch named 'pupr' for local commits,
    which drops the tracking information that was set up during checkout_branch.
    This restores the tracking config so that `git cl upload` targets the correct
    upstream branch (e.g. branch-heads/7827 instead of main) for non-repo projects.
    """
    if not (self.is_version_file_uprevver and self.properties.version_files and
            policy_info.branch):
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

  def _validate_properties(self) -> None:
    """Ensure the input properties look OK.

    Raises:
      StepFailure: if there are any issues with the input properties.
    """
    with self.m.step.nest('validate properties') as presentation:
      if self._is_package_uprevver and not self.properties.packages:
        raise recipe_api.StepFailure(
            'must set packages to uprev for a package uprevver')
      if self.is_version_file_uprevver and not self.properties.version_files:
        raise recipe_api.StepFailure(
            'must set version_files to uprev for a version file uprevver')

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
        if not policy.reviewers and not policy.gerrit_flow_expressions:
          raise recipe_api.StepFailure('need at least one reviewer or flow')

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
  def _raw_triggers(self) -> List[triggers_pb2.Trigger]:
    """Get the triggers which actually launched this run."""
    return self.properties.triggers or self.m.scheduler.triggers

  @property
  def _has_cron_trigger(self) -> bool:
    """Check whether any of this build's triggers is a cron trigger."""
    return any(trigger.HasField('cron') for trigger in self._raw_triggers)

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
      policy_infos: List[PolicyInfo] = []
      for trigger in self.triggers:
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

  def _read_gitiles(self, ref: str) -> Optional[str]:
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
    repo_url = None
    if self.is_version_file_uprevver:
      with self.m.context(cwd=self.m.cros_source.workspace_path):
        for v in self.properties.version_files:
          if not self.m.repo.project_exists(str(self.m.path.start_dir / v)):
            v_dir = self.m.path.dirname(self.m.path.start_dir / v)
            with self.m.context(cwd=v_dir):
              repo_url = self.m.step(
                  f'get remote url for {v}',
                  ['git', 'config', '--get', 'remote.origin.url'],
                  stdout=self.m.raw_io.output_text(), step_test_data=lambda:
                  self.m.raw_io.test_api.stream_output_text(
                      'https://chromium.googlesource.com/chromium/src.git'
                  )).stdout.strip()
            break

    with self.m.context(cwd=manifest.path):
      for policy in self.properties.branch_policies:
        if re.match(policy.pattern, tag):
          query = re.sub(policy.pattern, policy.repl, tag)
          if not query:
            return PolicyInfo(policy)
          refs = self.m.git.ls_remote([query], repo_url=repo_url)
          if len(refs) == 1:
            ref = refs[0]
            return PolicyInfo(policy, ref.ref.split('/')[-1], ref)
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
        needs_cros_checkout = True
        if self.is_version_file_uprevver and self.properties.version_files:
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
                    target_ref = target_ref.replace(
                        'refs/branch-heads/', 'refs/remotes/branch-heads/')
                    self.m.git.fetch(
                        remote='origin',
                        refs=[f'{policy_info.reference.ref}:{target_ref}'])
                    self.m.git.checkout(commit='FETCH_HEAD',
                                        branch=policy_info.branch)
                    self.m.step(
                        f'set upstream remote for {policy_info.branch}', [
                            'git', 'config',
                            f'branch.{policy_info.branch}.remote', 'origin'
                        ])
                    self.m.step(f'set upstream merge for {policy_info.branch}',
                                [
                                    'git', 'config',
                                    f'branch.{policy_info.branch}.merge',
                                    policy_info.reference.ref
                                ])
                    processed_non_repo_dirs.add(git_root)
        if needs_cros_checkout:
          self.m.cros_source.checkout_branch(
              self.m.src_state.internal_manifest.url, policy_info.branch)
      elif self._is_sdk_uprevver:
        # b/372434018: The source tree here should be identical to the SDK
        # builder's, unless policy overrides that. The SDK builder's uprevs
        # use source tree state for dependency invalidation through packages
        # like virtual/rust.
        #
        # The SDK builder uses the same mechanism as the CQ for passing source
        # state around.
        self.m.cros_source.sync_checkout(self.m.src_state.gitiles_commit)
      else:
        pres.step_text = 'using default branch'

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
      self.policy.topic = f'testing-{self.topic}'

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
                  gerrit_flow_expressions=(
                      '[{"condition": "-label:Commit-Queue", "action": '
                      '{"name": "add-reviewer", "parameters": '
                      '["cros-ec-champion@google.com"]}}]'),
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
          'select policy.check if project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM exists.repo info',
          api.raw_io.stream_output_text(
              'project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM not found',
              stream='stderr'),
          retcode=1,
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
      remote='cros',
      path='src/third_party/chromiumos-overlay',
      name='chromiumos/overlays/chromiumos-overlay',
      ref='refs/heads/main',
  )

  revision = '83a1812dddfc24f604d92bf61ad58efe9227a6fc'
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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
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
          'find open uprev CLs.find CLs from chromium host',
          [],
          'https://chromium-review.googlesource.com',
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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          [
              bb_common_pb2.GerritChange(
                  change=1, host='chromium-review.googlesource.com')
          ],
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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          changes,
          value_dict,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
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
          'check concurrent CQ runs',
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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          changes,
          value_dict,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.get CL 1 description',
          changes,
          value_dict,
      ),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.test gerrit mergeable',
          'chromium-review.googlesource.com',
          1,
          'current',
          False,
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
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']),
      api.post_check(
          post_process.StepSuccess,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1',
      ),
      # Commit message should contain the same version label as the original.
      # The change should be uploaded as a new patch set for the same Change-Id.
      api.post_check(
          post_process.StepCommandRE,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.commit uprev.commit in overlay.write commit message',
          [
              '.*',
              '.*',
              '.*',
              '.*',
              '.*',
              '.*',
              r'(.|\n)*' + pupr_local_uprev_api.UPREV_VERSION_LABEL + '.*' +
              revision + r'(.|\n)*Change-Id: deadbeef(.|\n)*',
              '.*',
          ],
      ),
      api.post_check(
          post_process.MustRunRE,
          r'.*upload patch set for Change-Id 1\.git_cl upload',
      ),
  )

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
          'revision_info': {
              'ref': 'refs/change/foo',
          },
      },
      2: {
          'change_id': 2,
          'created': '2020-10-23 18:54:00.000000000',
          'messages': [
              {
                  'message':
                      'Quote: Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
                  'date':
                      '2020-10-26T18:54:00Z',
              },
              {
                  'message':
                      'Patch Set 3:\n\nDry run: CV is trying the patch...',
                  'date':
                      '2020-10-24T18:54:00Z',
                  'tag':
                      'autogenerated:cv:dry-run:1000000001',
              },
              {
                  'message': 'Patch Set 3:\n\nThis CL has passed the run',
                  'date': '2020-10-25T18:54:00Z',
                  'tag': 'autogenerated:cv:dry-run:1000000002',
              },
          ],
          'revision_info': {
              'ref': 'refs/change/foo',
          },
      },
  }

  value_dict_wip = dict(value_dict)
  value_dict_wip[1] = dict(value_dict[1])
  value_dict_wip[1]['status'] = 'NEW'
  value_dict_wip[1]['hashtags'] = ['pupr-retry-pinned']
  value_dict_wip[1]['work_in_progress'] = True
  value_dict_wip[1]['revision_info'] = {
      'ref': 'refs/change/foo',
      'commit': {
          'message':
              'a quick description\n\nChange-Id: deadbeef\n\nPupr-Upstream-Versions: [{"ref": "refs/heads/main", "repository": "https://chromium.googlesource.com/chromium/src", "revision": "'
              + revision + '"}]',
      },
  }

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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          changes,
          value_dict_wip,
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.get CL 1 description',
          changes,
          value_dict_wip,
      ),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.test gerrit mergeable',
          'chromium-review.googlesource.com',
          1,
          'current',
          True,
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
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']),
      api.repo.project_infos_step_data(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.commit uprev',
          data=[{
              'project': 'overlay',
              'path': 'src/third_party/chromiumos-overlay',
          }],
      ),
      api.repo.project_infos_step_data(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.upload patch set for Change-Id 1',
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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          changes,
          value_dict_wip,
      ),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json,
          'https://chromium-review.googlesource.com',
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
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          changes,
          value_dict,
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
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
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
      api.step_data(
          'select policy.check if project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM exists.repo info',
          api.raw_io.stream_output_text(
              'project [START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM not found',
              stream='stderr'),
          retcode=1,
      ),
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
