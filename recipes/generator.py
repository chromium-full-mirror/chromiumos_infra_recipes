# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the PUpr generator.

PUpr is a general uprev pipeline that listens for package releases (via LUCI
Scheduler gitiles triggers), generates ebuild uprev CLs for those releases,
and tags the appropriate reviewers. Think of it as the CrOS autoroller.

See go/pupr and go/pupr-generator for rationale and design decisions.
"""

import json
import copy
import re
from collections import defaultdict
from functools import cached_property
from typing import DefaultDict, Dict, List, NamedTuple, Optional

from urllib import parse
from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromite.api.packages import UprevVersionedPackageResponse
from PB.chromite.api.packages import UprevPackagesResponse
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import CronTrigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import GitilesTrigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import Trigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import WebUITrigger
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
from PB.recipes.chromeos.generator import OutdatedClsPolicy
from PB.recipes.chromeos.generator import RETRY_LATEST_OR_LATEST_PINNED
from PB.recipes.chromeos.generator import RetryClPolicy
from PB.recipes.chromeos.generator import RetryRef
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from PB.recipes.chromeos.generator import SendToCqPolicy
from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet
from RECIPE_MODULES.chromeos.git.api import Reference
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

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
    'repo',
    'src_state',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GeneratorProperties

# HOSTS_REMOTES contains tuples (host, remote) representing our Gerrit
# instances, where host the section of the Gerrit URL that would be formatted
# into f'https://{host}-review.googlesource.com', and remote is the name of that
# host'secorresponding git remote.
HOSTS_REMOTES = (('chromium', 'cros'), ('chrome-internal', 'cros-internal'))

# The label written in the commit message to store versions information of
# upstream repositories given by gitiles trigger.
UPREV_VERSION_LABEL = 'Pupr-Upstream-Versions'


def RunSteps(api: RecipeApi, properties: GeneratorProperties):
  GeneratorRun(api, properties).run()


class Ebuild(NamedTuple):
  path: str
  version: str
  commit_info: str


class PolicyInfo(NamedTuple):
  policy: BranchPolicy
  branch: str = ''
  reference: Optional[Reference] = None


EbuildsByPinfo = DefaultDict[ProjectInfo, List[Ebuild]]


class GeneratorRun:
  """A single run of a Generator builder."""

  def __init__(self, api: RecipeApi, properties: GeneratorProperties):
    """Initialize the builder."""
    self.m = api
    self.properties = properties

    self.workspace_path: Optional[Path] = None
    self._policy: Optional[BranchPolicy] = None
    self.ebuilds_by_pinfo: Optional[EbuildsByPinfo] = None

    # If we see gitiles_info populated in the recipe properties, we will be
    # performing a fetch from the Gitiles API for the package's target uprev
    # version. This information will be used in branch determination and sent to
    # the uprev handler.
    self.gitiles_response = None

  @cached_property
  def triggers(self) -> List[Trigger]:
    """Get this run's triggers, all of which have the gitiles field set."""
    if self._has_cron_trigger:
      return [
          Trigger(gitiles=GitilesTrigger(ref=self.properties.retry_ref.ref))
      ]
    return self._raw_triggers

  @property
  def retry_only_run(self) -> bool:
    """Check whether this is a retry-only run."""
    return self._has_cron_trigger

  @property
  def packages(self) -> List[PackageInfo]:
    """Get the packages that this build should uprev."""
    if self.properties.HasField('package_info'):
      return [self.properties.package_info]
    return self.properties.packages

  @property
  def cpvs(self) -> List[str]:
    """Get the category-package-version for this build's packages."""
    return [
        self.m.naming.get_package_title(package) for package in self.packages
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
    return self.cpvs[0]

  @cached_property
  def _project_infos_by_remote(self) -> Dict[str, List[ProjectInfo]]:
    """Organize projects relevant to this run by remote."""
    project_infos_by_remote: DefaultDict[str, List[ProjectInfo]]
    project_infos_by_remote = defaultdict(list)
    if self.retry_only_run:
      project_infos_by_remote[self.properties.retry_ref.remote] = [
          self.m.repo.ProjectInfo(
              remote=self.properties.retry_ref.remote,
              name=self.properties.retry_ref.name,
              branch=self.properties.retry_ref.ref,
              rrev=self.properties.retry_ref.ref,
              path=self.properties.retry_ref.path,
          )
      ]
    else:
      assert self.ebuilds_by_pinfo is not None
      for info in sorted(self.ebuilds_by_pinfo):
        project_infos_by_remote[info.remote].append(info)
    return project_infos_by_remote

  def run(self):
    """Run the Generator."""
    self.m.cros_source.configure_builder(self.m.src_state.gitiles_commit,
                                         self.m.src_state.gerrit_changes)
    self.workspace_path = self.m.cros_source.workspace_path

    self._validate_properties()
    self._validate_triggers()

    with self.m.cros_source.checkout_overlays_context(), \
        self.m.cros_sdk.cleanup_context():
      self.m.cros_source.ensure_synced_cache(manifest_branch_override='main')

      policy_info = self.select_policy()
      self.set_policy(policy_info.policy)
      if self.policy.ignore:
        self.m.step.empty('policy set to ignore')
        return
      self.checkout_branch(policy_info)

      if self.m.cq.active or self.m.src_state.gerrit_changes:
        self.apply_gerrit_changes()

      if self.properties.init_sdk:
        with self.m.context(cwd=self.workspace_path):
          self.m.cros_sdk.create_chroot(use_image=False)

      if not self.retry_only_run:
        # If earlier we fetched for a target version through Gitiles, pass along
        # the retrieved value.
        versions = [
            UprevVersionedPackageRequest.GitRef(
                repository=parse.urlparse(trigger.gitiles.repo).path,
                ref=trigger.gitiles.ref, revision=(self.gitiles_response or
                                                   trigger.gitiles.revision))
            for trigger in self.triggers
        ]
        self.ebuilds_by_pinfo = self.uprev_packages(versions, change_id=None)
        if self.ebuilds_by_pinfo is None:
          return

      open_changes = self.find_open_uprev_cls()
      most_recent_uprev: Optional[PatchSet] = None
      if open_changes:
        most_recent_uprev = self.find_most_recently_merged_uprev()
      outdated_cls = self.get_outdated_cls(open_changes, most_recent_uprev)
      abandoned_cls = self._abandon_cls(outdated_cls, most_recent_uprev)
      existing_cls = bool(
          open_changes and len(abandoned_cls) < len(open_changes))

      if self.policy.retry_cl_policy != NO_RETRY:
        with self.m.step.nest('apply retry policy {}'.format(
            RetryClPolicy.Name(self.policy.retry_cl_policy))) as presentation:
          if open_changes:
            open_ci = self.m.gerrit.fetch_patch_sets(open_changes,
                                                     include_messages=True)
            if most_recent_uprev:
              open_ci = [
                  ci for ci in open_ci if ci.created > _get_outdated_timestamp(
                      most_recent_uprev, self.properties.rebase_before_retry)
              ]
            open_ci.sort(key=lambda ci: ci.created, reverse=True)

            if not self.m.pupr.retries_frozen(open_ci):
              patch_set_to_retry, cq_label, message, cl_passed_dry_run = self.m.pupr.identify_retry(
                  self.policy.retry_cl_policy,
                  self.policy.no_existing_cls_policy, open_ci)
              presentation.step_text = message

              if patch_set_to_retry:
                if self.properties.rebase_before_retry:
                  self.rebase_cl(open_changes, patch_set_to_retry.change_id)
                  with self.m.step.nest(
                      "upload patchset for Change-Id {}".format(
                          patch_set_to_retry.change_id)):
                    with self.m.context(cwd=self.workspace_path):
                      gerrit_change_to_retry = patch_set_to_retry.to_gerrit_change_proto(
                      )
                      project_info = self.m.repo.project_info(
                          gerrit_change_to_retry.project)
                      repository_path = self.m.path.join(
                          self.workspace_path, project_info.path)
                      with self.m.context(
                          cwd=self.m.path.abs_to_path(repository_path)):
                        self.m.git_cl.upload(send_mail=True)
                self.retry_cl(patch_set_to_retry, cq_label)
                if cl_passed_dry_run:
                  cls_to_abandon = [cl for cl in open_ci \
                      if cl.created < patch_set_to_retry.created]
                  self._abandon_cls(
                      cls_to_abandon, patch_set_to_retry,
                      step_name='abandon CLs before passed CQ+1 CL')
      if not self.retry_only_run:
        self._create_uprev_cls(open_changes, existing_cls)

  def rebase_cl(self, open_changes: List[GerritChange], change_id: str):
    """Upload a new uprev patch to change_id.

    Args:
      open_changes: List of currently open uprev CLs.
      change_id: ID of the CL to upload a new patch set for.
    """
    with self.m.step.nest("rebase CL {}".format(change_id)):
      retry_changes = [p for p in open_changes if p.change == change_id]
      assert len(retry_changes) == 1
      retry_change = retry_changes[0]
      # Extract Change-Id from commit message
      description = self.m.gerrit.get_change_description(retry_change)
      change_id = _extract_metadata(description, 'Change-Id: (.*)')
      existing_versions = _deserialize_versions(
          _extract_metadata(description, UPREV_VERSION_LABEL + ': (.*)'))
      ebuilds_by_pinfo = self.uprev_packages(existing_versions, change_id)
      if not ebuilds_by_pinfo:
        raise StepFailure('The uprev had no file.')
      if len(ebuilds_by_pinfo.keys()) > 1:
        raise StepFailure(
            'The uprev requires multi-repo commit. Cannot be rebased. {}'
            .format(sorted(ebuilds_by_pinfo.keys())))

  def uprev_packages(self, versions: List[UprevVersionedPackageRequest.GitRef],
                     change_id: Optional[str] = None
                    ) -> Optional[EbuildsByPinfo]:
    """Try the uprev for the given packages. If successful, commit the uprev.

    Args:
      versions: The versions to consider for an update.
      change_id: If not None, set Change-Id to the commit message, so that the
        commit is uploaded as a new patchset of an existing Change. When this is
        set, the uprev should not span multiple repositories.

    Returns:
      ebuilds_by_pinfo, or None. If None, pupr should return immediately.
    """
    modified_package_names: List[str] = []
    all_valid_responses: List[UprevPackagesResponse] = []
    for package in self.packages:
      package_responses = self.uprev_package(package, versions)
      if package_responses:
        all_valid_responses.extend(package_responses)
        modified_package_names.append(package.package_name)
      elif not self.properties.allow_partial_uprev:
        return None
    if not all_valid_responses:
      return None
    return self.commit_uprevs(versions, all_valid_responses,
                              modified_package_names, change_id=change_id)

  def uprev_package(
      self,
      package: PackageInfo,
      versions: List[UprevVersionedPackageRequest.GitRef],
  ) -> List[UprevPackagesResponse]:
    """Locally uprev a single package.

    Args:
      package: The package to uprev.
      versions: The versions to consider for an update.

    Returns:
      List of UprevPackageResponses that actually changed code.
    """
    cpv = self.m.naming.get_package_title(package)
    with self.m.step.nest('try uprev {}'.format(cpv)) as presentation:
      request = UprevVersionedPackageRequest(
          chroot=self.m.cros_sdk.chroot,
          package_info=package,
          versions=versions,
          build_targets=self.properties.build_targets,
      )
      presentation.logs['request'] = str(request)
      response = self.m.cros_build_api.PackageService.UprevVersionedPackage(
          request, name='uprev versioned package')

      if not response.responses:
        presentation.step_text = 'no new versions for {}'.format(cpv)
        return None

      valid_responses: List[UprevPackagesResponse] = []
      with self.m.step.nest('verify updates'):
        # only act on files that are actually modified
        for uprev_resp in response.responses:
          if _response_has_changes(self.m, uprev_resp):
            valid_responses.append(uprev_resp)

      if not valid_responses:
        presentation.step_text = (
            'skipping uprev for {}. no modified files'.format(cpv))
        if not self.properties.allow_partial_uprev:
          return []
        presentation.logs['partial_uprev'] = [
            'no modified file for {}. continue because allow_partial_uprev=True'
            .format(cpv)
        ]
        return []

      presentation.logs['uprev versions'] = [
          response.version for response in valid_responses
      ]
    return valid_responses

  def commit_uprevs(self, versions: List[UprevVersionedPackageRequest.GitRef],
                    uprev_packages_responses: List[UprevPackagesResponse],
                    modified_package_names: List[str],
                    change_id: Optional[str] = None
                   ) -> Optional[EbuildsByPinfo]:
    """Commit the uprevs on the local filesystem.

    Args:
      versions: The versions to consider for an update.
      uprev_packages_responses: BAPI responses for all uprevs that actually
          produced code changes.
      modified_package_names: The names of packages that are modified.
      change_id: If not None, set Change-Id to the commit message, so that the
        commit is uploaded as a new patchset of an existing Change. When this is
        set, the uprev should not span multiple repositories.

    Returns:
      ebuilds_by_pinfo, or None. If None, pupr should return immediately.
    """
    with self.m.step.nest('commit uprev'):
      # Flatten the list of modified files, and get the project info for them.
      modified_ebuilds: List[Ebuild] = []
      for uprev_resp in uprev_packages_responses:
        modified_ebuilds.extend(
            Ebuild(path=ebuild.path, version=uprev_resp.version,
                   commit_info=uprev_resp.additional_commit_info)
            for ebuild in uprev_resp.modified_ebuilds)
      with self.m.context(cwd=self.workspace_path):
        ebuilds_by_pinfo = EbuildsByPinfo(list)
        for ebuild in modified_ebuilds:
          dirname = self.m.path.dirname(ebuild.path)
          info = self.m.repo.project_infos(projects=[dirname])[0]
          ebuilds_by_pinfo[info].append(ebuild)

        # Checkout git branches via repo so they track correctly.  Create them
        # by path instead of project name, because they may be checked out
        # multiple times.
        self.m.repo.start(
            'pupr',
            projects=[info.path for info in sorted(ebuilds_by_pinfo.keys())])

      # For each repository, make the CL.
      for info, ebuilds in sorted(ebuilds_by_pinfo.items()):
        name = self.m.path.basename(info.path)
        root = self.workspace_path.join(info.path)
        vers = ', '.join(sorted({e.version for e in ebuilds}))

        additional_msg = ''
        if self.properties.additional_commit_message \
            and self.properties.additional_commit_message != '':
          additional_msg = self.properties.additional_commit_message + '\n'

        additional_commit_info = [
            e.commit_info for e in ebuilds if e.commit_info
        ]
        if additional_commit_info:
          additional_msg += '\n'.join(sorted(
              set(additional_commit_info))) + '\n'

        commit_lines = [
            '{package_name}: Automatic uprev to {versions}.'.format(
                package_name=', '.join(modified_package_names), versions=vers),
            '',
            '{additional_msg}Generated by PUpr, see {build_url} for job details.'
            .format(additional_msg=additional_msg,
                    build_url=self.m.buildbucket.build_url()),
            '',
            'BUG=None',
            'TEST=CQ',
            '',
            '{label}: {versions}'.format(
                label=UPREV_VERSION_LABEL,
                versions=_serialize_versions(versions)),
            'Cq-Cl-Tag: pupr:{topic}'.format(topic=self.topic),
        ]
        if self.m.src_state.gerrit_changes:
          commit_lines.append('Cq-Depend: {}'.format(','.join(
              '{}:{}'.format(
                  x.host.split('.', 1)[0].replace('-review', ''), x.change)
              for x in self.m.src_state.gerrit_changes)))
        if change_id is not None:
          commit_lines.append('Change-Id: ' + change_id)
        commit_message = '\n'.join(commit_lines) + '\n'

        with self.m.step.nest(
            'commit in {}'.format(name)), self.m.context(cwd=root):
          self.m.git.add([e.path for e in ebuilds])
          self.m.git.commit(commit_message)

    return ebuilds_by_pinfo

  def _validate_properties(self):
    """Ensure the input properties look OK.

    Raises:
      StepFailure: if there are any issues with the input properties.
    """
    with self.m.step.nest('validate properties') as presentation:
      if ((not self.properties.HasField('package_info') and
           not self.properties.packages) or
          (self.properties.HasField('package_info') and
           self.properties.packages)):
        raise StepFailure(
            'must set exactly one of {package_info, non-empty packages}')

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
        raise StepFailure('found no scheduler triggers')
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
            self.gitiles_response = gitiles_response.strip()

        # If we we recieved a target version from Gitiles, override the tag
        # argument.
        tag = self.gitiles_response or trigger.gitiles.ref
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

  def _create_uprev_cls(self, open_changes: List[GerritChange],
                        existing_cls: bool):
    """Create appropriate CLs for the uprevs."""
    send_to_cq_policy = (
        self.policy.existing_cls_policy
        if existing_cls else self.policy.no_existing_cls_policy)

    with self.m.step.nest('generate CLs'):
      changes = []
      assert self.ebuilds_by_pinfo is not None
      for info in sorted(self.ebuilds_by_pinfo):
        changes.append(
            self.m.gerrit.create_change(
                info.path,
                reviewers=[
                    reviewer.email for reviewer in self.policy.reviewers
                ],
                topic=self.topic,
            ))
      self.m.easy.set_properties_step(
          generated_cls=[MessageToDict(change) for change in changes])

    if changes:
      with self.m.step.nest('cq-depend generated CLs'):
        cq_depends = self.m.cros_cq_depends.get_mutual_cq_depend(changes)
        for change, cq_depend in zip(changes, cq_depends):
          with self.m.step.nest('set cq-depend for {} CL'.format(
              change.project)) as presentation:
            if not cq_depend:
              presentation.step_text = "empty Cq-Depend, skipping"
              continue
            description = self.m.gerrit.get_change_description(change)
            description = self.m.git_footers.edit_add_change_description(
                description, 'Cq-Depend', cq_depend)
            self.m.gerrit.set_change_description(change, description,
                                                 amend_local=True)

    with self.m.step.nest('update CL labels'):
      for change in changes:
        # First post explanatory message.
        message_lines = [
            'Found {} open CL(s) for Gerrit topic {}:'.format(
                len(open_changes), self.topic),
            '\n'.join(map(self.m.gerrit.parse_gerrit_change_url, open_changes)),
            'Send-to-cq policy for this case is {}.'.format(
                SendToCqPolicy.Name(send_to_cq_policy))
        ]

        message_lines.append({
            DRY_RUN: 'Therefore, marking CL as CQ+1',
            FULL_RUN: 'Therefore, marking CL as CQ+2',
            ABANDON: 'Therefore, abandoning the CL',
            SUBMIT: 'Therefore, will attempt to directly submit the CL.',
        }.get(
            send_to_cq_policy,
            'Therefore, will NOT mark CL as CQ+1/CQ+2. Reviewers must do so. '
            'Reviewers may also want to abandon the open CL(s).',
        ))

        message = '\n'.join(message_lines)
        if send_to_cq_policy == ABANDON:
          self.m.gerrit.abandon_change(change, message=message)
        else:
          self.m.gerrit.add_change_comment(change, message)

        # Then set labels.
        labels = {
            DRY_RUN: {
                Label.BOT_COMMIT: 1,
                Label.COMMIT_QUEUE: 1,
            },
            FULL_RUN: {
                Label.BOT_COMMIT: 1,
                Label.COMMIT_QUEUE: 2,
            },
            SUBMIT: {
                Label.BOT_COMMIT: 1,
            },
        }.get(send_to_cq_policy)

        if labels is not None:
          self.m.gerrit.set_change_labels(change, labels)

      if send_to_cq_policy == SUBMIT:
        with self.m.step.nest('submit CL'):
          self.m.gerrit.submit_change(change)

  def get_outdated_cls(self, open_changes: List[GerritChange],
                       most_recent_uprev: Optional[PatchSet]) -> List[PatchSet]:
    """Query Gerrit to find all CLs older than the most recently merged.

    Args:
      most_recent_uprev: The relevant uprev CL which was most recently merged.

    Returns:
      A list of CLs which were created before most_recent_uprev was either
      created or submitted. (We compare against most_recent_uprev's either
      created timestamp or submitted timestamp, depending on
      properties.rebase_before_retry.)
    """
    if not most_recent_uprev:
      return []
    open_patch_sets = self.m.gerrit.fetch_patch_sets(open_changes)
    with self.m.step.nest('outdated CLs') as presentation:
      outdated_cls = [
          cl for cl in open_patch_sets if cl.created < _get_outdated_timestamp(
              most_recent_uprev, self.properties.rebase_before_retry)
      ]
      presentation.logs['outdated CLs'] = [cl.display_id for cl in outdated_cls]
    return outdated_cls

  def _abandon_cls(self, outdated_cls: List[PatchSet],
                   most_recent_uprev: PatchSet,
                   step_name: Optional[str] = None) -> List[PatchSet]:
    """Abandon uprev CLs according to the outdated_cls_policy.

    Args:
      outdated_cls: Open uprev CLs that are behind the most recent merge.
      most_recent_uprev: The most recent merged uprev CL.
      step_name: Option to override the step name for this abandonment.

    Returns:
      List of CLs which have been abandoned.
    """
    if not outdated_cls:
      return []
    abandoned_cls: List[PatchSet] = []
    if step_name is None:
      step_name = 'act on outdated CLs with policy: {}'.format(
          OutdatedClsPolicy.Name(self.policy.outdated_cls_policy))
    with self.m.step.nest(step_name):
      for outdated_cl in outdated_cls:
        if self.policy.outdated_cls_policy == OUTDATED_LEAVE_COMMENT and not self.retry_only_run:
          outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                      'PUpr has been set to remind you that it'
                                      ' likely should be abandoned.').format(
                                          most_recent_uprev.display_url)
          self.m.gerrit.add_change_comment(outdated_cl.to_gerrit_change_proto(),
                                           outdated_comment_message)
        elif self.policy.outdated_cls_policy == OUTDATED_ABANDON:
          outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                      'PUpr has been set to abandon.').format(
                                          most_recent_uprev.display_url)
          self.m.gerrit.abandon_change(outdated_cl.to_gerrit_change_proto(),
                                       message=outdated_comment_message)
          abandoned_cls.append(outdated_cl)
    return abandoned_cls

  def find_open_uprev_cls(self) -> List[GerritChange]:
    """Return any open uprev CLs matching the same topic as this run."""
    open_changes: List[GerritChange] = []
    with self.m.step.nest('find open uprev CLs'):
      for host, remote in HOSTS_REMOTES:
        with self.m.step.nest('find CLs from {} host'.format(host)):
          host_url = 'https://{}-review.googlesource.com'.format(host)
          for info in self._project_infos_by_remote[remote]:
            open_changes.extend(
                self.m.gerrit.query_changes(host_url,
                                            [('topic', self.topic),
                                             ('project', info.name),
                                             ('branch', info.branch_name),
                                             ('status', 'open')]))
    return open_changes

  def find_most_recently_merged_uprev(self) -> Optional[PatchSet]:
    """Return the most recently merged relevant uprev as queried from Gerrit."""
    most_recent_uprev: Optional[PatchSet] = None
    with self.m.step.nest('examine outdated CLs'):
      for host, remote in HOSTS_REMOTES:
        with self.m.step.nest('merged CLs from {} host (within 30 days)'.format(
            host)) as presentation:
          host_url = 'https://{}-review.googlesource.com'.format(host)
          merged_changes = []
          for project_info in self._project_infos_by_remote[remote]:
            merged_changes.extend(
                self.m.gerrit.query_changes(
                    host_url, [('topic', self.topic),
                               ('project', project_info.name),
                               ('branch', project_info.branch_name),
                               ('status', 'merged'), ('-age', '30d')]))
          if merged_changes:
            presentation.logs['merged CLs'] = [
                self.m.gerrit.parse_gerrit_change_url(cl)
                for cl in merged_changes
            ]
            # Must fetch to get submitted times from the "PatchSets", which are
            # really instances of ChangeInfo.
            merged_change_infos = self.m.gerrit.fetch_patch_sets(merged_changes)
            merged_change_infos.sort(key=lambda ci: ci.submitted, reverse=True)
            if merged_change_infos:
              most_recent_uprev = merged_change_infos[0]
              presentation.logs['most recent merged cl'] = [
                  most_recent_uprev.display_id
              ]
          else:
            presentation.step_text = 'no merged CLs found'
            presentation.status = self.m.step.WARNING
    return most_recent_uprev

  def retry_cl(self, patch_set: PatchSet, cq_label: int):
    """Retry sending the CL through CQ by setting its Gerrit labels."""
    with self.m.step.nest("retry CL {}".format(patch_set.change_id)):
      labels = {
          Label.BOT_COMMIT: 1,
          Label.COMMIT_QUEUE: cq_label,
      }
      gerrit_change = patch_set.to_gerrit_change_proto()
      with self.m.context(cwd=self.workspace_path):
        project_info = self.m.repo.project_info(gerrit_change.project)
        repo_path = self.m.path.join(self.workspace_path, project_info.path)
        with self.m.context(cwd=self.m.path.abs_to_path(repo_path)):
          self.m.gerrit.set_change_labels_remote(gerrit_change, labels)


def _serialize_versions(versions: List[UprevVersionedPackageRequest.GitRef]
                       ) -> str:
  """Serialize versions information.

  Args:
    versions: The versions to consider for an update.

  Returns:
    A JSON string that encodes the input.
  """
  o = [{
      'ref': v.ref,
      'repository': v.repository,
      'revision': v.revision,
  } for v in versions]
  return json.dumps(o)


def _deserialize_versions(json_str: str
                         ) -> List[UprevVersionedPackageRequest.GitRef]:
  """Deserialize versions information.

  Args:
    json_str: A string serialized by serializeVersions().

  Returns:
    The versions to consider for an uprev.
  """
  objs = json.loads(json_str)
  return [
      UprevVersionedPackageRequest.GitRef(
          repository=o.get('repository'), ref=o.get('ref'),
          revision=o.get('revision')) for o in objs
  ]


def _extract_metadata(description: str, pattern: str) -> str:
  """Retrieves a single piece of metadata from a CL description.

  Args:
    description: The CL's commit message.
    pattern: A string representing a regex pattern, with a single capture group.
  """
  m = re.findall(pattern, description)
  if len(m) != 1:
    raise StepFailure(
        'failed to find a single pattern {} in the Change description (found {}): {}'
        .format(pattern, len(m), description))
  return m[0]


# TODO(dburger): deleted files should be at the end of the modified_ebuilds list
# to work correctly with api.git.diff_check.
def _response_has_changes(api: RecipeApi,
                          response: UprevVersionedPackageResponse) -> bool:
  """Returns whether the given `UprevVersionedPackageResponse` contains changes."""
  for ebuild in response.modified_ebuilds:
    path = ebuild.path
    with api.context(cwd=api.path.abs_to_path(api.path.dirname(path))):
      if api.git.diff_check(path):
        return True
  return False


def _get_outdated_timestamp(most_recent_uprev: Optional[PatchSet],
                            rebase_before_retry: bool) -> str:
  """Determine the cutoff time at which CLs become outdated.

  Args:
    most_recent_uprev: The most recently merged relevant uprev.
    rebase_before_retry: See generator.proto.

  Returns:
    A timestamp string, in the same format as PatchSet.created, after which any
    CL would be considered outdated.
  """
  if rebase_before_retry:
    return most_recent_uprev.created
  return most_recent_uprev.submitted


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
          'package_info',
          PackageInfo(category='chromeos-base', package_name='chromite'))
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
  )

  yield api.test(
      'no-matching-policy',
      _props(branch_policies=[]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun, 'set policy'),
  )

  yield api.test(
      'no-package-info',
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'no-reviewers',
      _props(branch_policies=[_policy(reviewers=None)]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'blank-reviewer',
      _props(branch_policies=[_policy(reviewers=[{}])]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'non-gitiles-triggers',
      _props(),
      api.scheduler(triggers=[
          Trigger(id='456', webui=WebUITrigger()),
      ]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
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
          package_info=package_chrome, branch_policies=[
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
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'checkout branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield _with_infos(
      'branch-policies-multiple-triggers',
      api.properties(triggers=[trigger_prop] * 2),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'checkout branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multiple-trigger-policies',
      api.properties(triggers=[trigger_prop, trigger_prop2]),
      _props(package_info=package_chrome,
             branch_policies=[branch_policy, _policy()]),
      api.post_check(post_process.MustRun, 'select policy.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-no-pattern',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[no_pattern_policy]),
      api.post_check(post_process.DoesNotRun, 'select policy.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-default-branch',
      api.properties(triggers=[trigger_prop]),
      _props(
          package_info=package_chrome, branch_policies=[
              BranchPolicy(pattern='.*', repl='',
                           reviewers=[Reviewer(email='a@example.com')])
          ]),
      api.post_check(post_process.DoesNotRun, 'select policy.git ls-remote'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multi-ref',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.step_data(
          'select policy.git ls-remote',
          stdout=api.raw_io.output_text('\n'.join([
              '9ed37bc6f515ef0ef42949d9f23e1180432649f5\t'
              'refs/remotes/cros-internal/release-R79-5555.B',
              'f3ecd792bc4822dd6686313478099b8eb3df7e55\t'
              'refs/remotes/cros-internal/release-R79-9999.B',
              '',
          ]))),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield _with_infos(
      'additional-commit-message',
      _props(additional_commit_message='TEST'),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in overlay.write commit message',
          ['.*', '.*', '.*', '.*', '.*', '.*', r'(?s).*\n\nTEST\n.*', '.*']),
  )

  yield _with_infos(
      'multiple-packages', api.properties(triggers=[trigger_prop]),
      _props(
          packages=[
              package_chrome,
              PackageInfo(category='chromeos-base',
                          package_name='chromeos-lacros'),
          ],
          package_info=None,
          topic='chromeos-base/new-topic-name',
      ), api.git.diff_check(True),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-chrome'),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-lacros'),
      api.post_check(post_process.StatusSuccess),
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

  yield api.test(
      'allow-partial-uprev',
      api.repo.project_infos_step_data('commit uprev', data=[
          dict(project='overlay'),
      ], iteration=1),
      api.repo.project_infos_step_data('commit uprev', data=[
          dict(project='overlay'),
      ], iteration=2),
      _props(
          packages=[
              package_chrome,
              PackageInfo(category='chromeos-base',
                          package_name='chromeos-lacros'),
          ], package_info=None, topic='chromeos-base/new-topic-name',
          allow_partial_uprev=True),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-chrome'),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-lacros'),
      api.git.step_data(
          'try uprev chromeos-base/chromeos-chrome.verify updates.diff check.git diff',
          retcode=False),
      api.git.step_data(
          'try uprev chromeos-base/chromeos-lacros.verify updates.diff check.git diff',
          retcode=True),
      api.post_check(
          post_process.StepCommandContains,
          'generate CLs.create gerrit change for src/overlay.git_cl upload',
          ['--topic', 'chromeos-base/new-topic-name']),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'allow-partial-uprev-no-update',
      _props(
          packages=[
              package_chrome,
              PackageInfo(category='chromeos-base',
                          package_name='chromeos-lacros'),
          ], package_info=None, topic='chromeos-base/new-topic-name',
          allow_partial_uprev=True),
      api.git.diff_check(False),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-chrome'),
      api.post_check(post_process.MustRun,
                     'try uprev chromeos-base/chromeos-lacros'),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'duplicated-package-info-and-packages',
      _props(package_info=package_chrome, packages=[package_chrome],
             branch_policies=[_policy(ignore=True)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.post_check(post_process.StatusAnyFailure),
  )

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
          'messages': [{
              'message':
                  'Quote: Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-26T18:54:00Z',
          }, {
              'message': 'Patch Set 3:\n\nCV is trying the patch...',
              'date': '2020-10-24T18:54:00Z',
              'tag': 'autogenerated:cv:full-run'
          }, {
              'message':
                  'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-25T18:54:00Z',
              'tag':
                  'autogenerated:cv:full-run'
          }],
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
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [], 'https://chromium-review.googlesource.com', {}),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chrome-internal host (within 30 days)',
          [], 'https://chrome-internal-review.googlesource.com', {}),
      api.post_check(post_process.DoesNotRun, 'outdated CLs'),
      api.post_check(post_process.StatusSuccess),
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
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
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
              'tag': 'autogenerated:cv:full-run'
          }, {
              'message':
                  'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-25T18:54:00Z',
              'tag':
                  'autogenerated:cv:full-run'
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
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
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
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']),
      api.post_check(
          post_process.StepSuccess,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1'),
      # Commit message should contain the same version label as the original.
      # The change should be uploaded as a new patchset for the same Change-Id.
      api.post_check(
          post_process.StepCommandRE,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.commit uprev.commit in overlay.write commit message',
          [
              '.*', '.*', '.*', '.*', '.*', '.*',
              r'(.|\n)*' + UPREV_VERSION_LABEL + '.*' + revision +
              r'(.|\n)*Change-Id: deadbeef(.|\n)*', '.*'
          ]),
      api.post_check(post_process.MustRunRE,
                     r'.*upload patchset for Change-Id 1\.git_cl upload'))

  yield api.test(
      'cron-trigger-rebase-no-diff',
      _props(
          branch_policies=[
              _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                      existing_cls_policy=DRY_RUN,
                      no_existing_cls_policy=DRY_RUN)
          ], retry_ref=retry_ref, rebase_before_retry=True),
      api.scheduler(triggers=[Trigger(cron=CronTrigger(generation=-1))]),
      api.git.diff_check(False),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.get CL 1 description',
          changes, value_dict),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
      api.post_check(
          post_process.StepFailure,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1'),
  )

  yield api.test(
      'cron-trigger-rebase-multi-repo',
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
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
      # The default of mocked UprevVersionedPackage updates multiple repos.
      # Current implementation does not support rebasing CLs in such a case.
      api.post_check(
          post_process.StepFailure,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1'),
  )

  value_dict2 = copy.deepcopy(value_dict)
  # missing versions data in CL description.
  value_dict2[1]['revision_info']['commit'][
      'message'] = 'CL Description\n\nChange-Id: f00'
  yield api.test(
      'cron-trigger-rebase-no-data',
      _props(
          branch_policies=[
              _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                      existing_cls_policy=DRY_RUN,
                      no_existing_cls_policy=DRY_RUN)
          ], retry_ref=retry_ref, rebase_before_retry=True),
      api.scheduler(triggers=[Trigger(cron=CronTrigger(generation=-1))]),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict2),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1.get CL 1 description',
          changes, value_dict2),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
      api.post_check(
          post_process.StepFailure,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1'),
  )

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
              'tag': 'autogenerated:cv:full-run'
          }, {
              'message':
                  'Patch Set 3:\n\nThis CL has failed the run. Reason: ...',
              'date':
                  '2020-10-25T18:54:00Z',
              'tag':
                  'autogenerated:cv:full-run'
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
              'tag': 'autogenerated:cv:dry-run'
          }, {
              'message': 'Patch Set 3:\n\nThis CL has passed the run',
              'date': '2020-10-25T18:54:00Z',
              'tag': 'autogenerated:cv:dry-run'
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
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
      api.gerrit.set_query_changes_response(
          'find open uprev CLs.find CLs from chromium host',
          gerrit_changes_json, 'https://chromium-review.googlesource.com',
          value_dict),
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
