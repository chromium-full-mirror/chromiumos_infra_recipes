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
from typing import DefaultDict, List, NamedTuple, Optional

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
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
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

  def run(self):
    """Run the Generator."""
    self.m.cros_source.configure_builder(self.m.src_state.gitiles_commit,
                                         self.m.src_state.gerrit_changes)
    workspace_path = self.m.cros_source.workspace_path

    self._validate_properties()
    self._validate_triggers()

    with self.m.cros_source.checkout_overlays_context(), \
        self.m.cros_sdk.cleanup_context():
      self.m.cros_source.ensure_synced_cache(manifest_branch_override='main')

      # Check out the appropriate branch, and use the appropriate policy.
      # If gitiles_info is given to us then we will determine the branch based on
      # the information returned by the Gitiles API. Otherwise, use the gitles.ref
      # seen in the trigger.
      with self.m.step.nest('determine branch') as pres:
        trigger_policies = []
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
          policy_info = self._get_policy(tag)
          if policy_info not in trigger_policies:
            trigger_policies.append(policy_info)
        # If we match more than one policy with the triggers, that is an error.
        # For Chrome, we are launched with properties.triggers, for exactly one
        # version.  See http://shortn/_qWgYUlVY6X in trigger_official_builds().
        if len(trigger_policies) > 1:
          raise StepFailure('too many triggers')
        policy_info = trigger_policies.pop()
        policy = policy_info.policy

        if policy.ignore:
          pres.step_text = 'policy set to ignore.'
          return

        if policy_info.branch:
          assert policy_info.reference is not None
          pres.step_text = 'using {} {}'.format(policy_info.branch,
                                                policy_info.reference.hash)
          self.m.cros_source.checkout_branch(
              self.m.src_state.internal_manifest.url, policy_info.branch)
        else:
          pres.step_text = 'using default branch'
      self.m.easy.set_properties_step(policy=MessageToDict(policy))

      base_topic_name = self.properties.topic or self.cpvs[0]
      if self.m.cq.active or self.m.src_state.gerrit_changes:
        # Use case: Developer is working on the versioned uprev code for a
        # package, such as Chrome, and wants to test the changes prior to landing
        # them in chromite.  While launching a build with the correct polcies and
        # triggers is difficult in CQ, it is rather straightforward for the dev to
        # manually launch the build with "correct" inputs.  On the other hand, we
        # should not produce production effects with uncommitted changes.
        #
        # If there are gerrit_changes to apply, log the chosen policy, and then
        # override the policy so that we do not submit, abandon, or comment on
        # anything.
        with self.m.step.nest('apply gerrit changes'):
          if self.m.src_state.gerrit_changes:
            self.m.cros_source.apply_gerrit_changes(
                self.m.src_state.gerrit_changes)
          with self.m.step.nest('update policy') as pres:
            user = self.m.buildbucket.build.created_by.replace('user:', '', 1)
            self.m.easy.set_properties_step(
                original_policy=MessageToDict(policy))
            del policy.reviewers[:]
            policy.reviewers.add().email = user
            policy.existing_cls_policy = ABANDON
            policy.no_existing_cls_policy = ABANDON
            policy.outdated_cls_policy = OUTDATED_DO_NOTHING
            policy.retry_cl_policy = NO_RETRY
            policy.topic = '{}-{}'.format('testing', policy.topic or
                                          base_topic_name)
            self.m.easy.set_properties_step(policy=MessageToDict(policy))

      if self.properties.init_sdk:
        with self.m.context(cwd=workspace_path):
          self.m.cros_sdk.create_chroot(use_image=False)

      topic = policy.topic or base_topic_name
      no_existing_cls_policy = policy.no_existing_cls_policy
      outdated_cls_policy = policy.outdated_cls_policy
      retry_cl_policy = policy.retry_cl_policy or NO_RETRY

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
        ebuilds_by_pinfo = self.uprev_packages(workspace_path, versions, topic,
                                               change_id=None)
        if ebuilds_by_pinfo is None:
          return

      pinfos_by_remote = defaultdict(list)
      if not self.retry_only_run:
        assert ebuilds_by_pinfo is not None
        for info in sorted(ebuilds_by_pinfo.keys()):
          pinfos_by_remote[info.remote].append(info)
      else:
        pinfos_by_remote[self.properties.retry_ref.remote] = [
            self.m.repo.ProjectInfo(
                remote=self.properties.retry_ref.remote,
                name=self.properties.retry_ref.name,
                branch=self.properties.retry_ref.ref,
                rrev=self.properties.retry_ref.ref,
                path=self.properties.retry_ref.path,
            )
        ]

      with self.m.step.nest('find open uprev CLs'):
        open_changes: List[GerritChange] = []
        for host, remote in (('chromium', 'cros'), ('chrome-internal',
                                                    'cros-internal')):
          with self.m.step.nest('find CLs from {} host'.format(host)):
            host_url = 'https://{}-review.googlesource.com'.format(host)
            for info in pinfos_by_remote[remote]:
              open_changes.extend(
                  self.m.gerrit.query_changes(host_url,
                                              [('topic', topic),
                                               ('project', info.name),
                                               ('branch', info.branch_name),
                                               ('status', 'open')]))

      mrm = None  # Most recently merged uprev.
      if open_changes:
        with self.m.step.nest('examine outdated CLs'):
          for host, remote in (('chromium', 'cros'), ('chrome-internal',
                                                      'cros-internal')):
            with self.m.step.nest(
                'merged CLs from {} host (within 30 days)'.format(
                    host)) as presentation:
              host_url = 'https://{}-review.googlesource.com'.format(host)
              merged_changes = []
              for info in pinfos_by_remote[remote]:
                merged_changes.extend(
                    self.m.gerrit.query_changes(host_url,
                                                [('topic', topic),
                                                 ('project', info.name),
                                                 ('branch', info.branch_name),
                                                 ('status', 'merged'),
                                                 ('-age', '30d')]))

              if merged_changes:
                presentation.logs['merged CLs'] = [
                    self.m.gerrit.parse_gerrit_change_url(cl)
                    for cl in merged_changes
                ]

                # Must fetch to get submitted times from the "PatchSets", which
                # are really instances of ChangeInfo.
                merged_ci = self.m.gerrit.fetch_patch_sets(merged_changes)
                list.sort(merged_ci, key=lambda ci: ci.submitted, reverse=True)
                mrm = merged_ci[0] if merged_ci else None
                presentation.logs['most recent merged cl'] = [mrm.display_id]
              else:
                presentation.step_text = 'no merged CLs found'
                presentation.status = self.m.step.WARNING

      outdated_cls: List[PatchSet] = []
      abandoned_cls: List[PatchSet] = []
      if mrm:
        open_ci = self.m.gerrit.fetch_patch_sets(open_changes)
        with self.m.step.nest('outdated CLs') as presentation:
          d = mrm.created if self.properties.rebase_before_retry else mrm.submitted
          outdated_cls.extend([ci for ci in open_ci if ci.created < d])
          presentation.logs['outdated CLs'] = [
              ci.display_id for ci in outdated_cls
          ]

      if outdated_cls:
        with self.m.step.nest('act on outdated CLs with policy: {}'.format(
            OutdatedClsPolicy.Name(outdated_cls_policy))) as pres:
          _abandon_cls(self.m, outdated_cls, mrm, outdated_cls_policy, \
              self.retry_only_run, abandoned_cls)

      existing_cls = bool(
          open_changes and len(abandoned_cls) < len(open_changes))

      if retry_cl_policy != NO_RETRY:
        with self.m.step.nest('apply retry policy {}'.format(
            RetryClPolicy.Name(retry_cl_policy))) as presentation:
          if open_changes:
            open_ci = self.m.gerrit.fetch_patch_sets(open_changes,
                                                     include_messages=True)
            # Filter out outdated CLs, sort by recency
            d = mrm.created if self.properties.rebase_before_retry else mrm.submitted
            if mrm:
              open_ci = [ci for ci in open_ci if ci.created > d]
            open_ci = sorted(open_ci, key=lambda ci: ci.created, reverse=True)

            if not self.m.pupr.retries_frozen(open_ci):
              retry_ci, cq_label, message, retry_cl_is_passed = self.m.pupr.identify_retry(
                  retry_cl_policy, no_existing_cls_policy, open_ci)
              presentation.step_text = message

              if retry_ci:
                if self.properties.rebase_before_retry:
                  self.rebase_cl(open_changes, retry_ci.change_id,
                                 workspace_path, topic)
                  with self.m.step.nest(
                      "upload patchset for Change-Id {}".format(
                          retry_ci.change_id)):
                    with self.m.context(cwd=workspace_path):
                      retry_cl = retry_ci.to_gerrit_change_proto()
                      project_info = self.m.repo.project_info(retry_cl.project)
                      repository_path = self.m.path.join(
                          workspace_path, project_info.path)
                      with self.m.context(
                          cwd=self.m.path.abs_to_path(repository_path)):
                        self.m.git_cl.upload(send_mail=False)

                with self.m.step.nest("retry CL {}".format(retry_ci.change_id)):
                  labels = {
                      self.m.gerrit.Label.BOT_COMMIT: 1,
                      self.m.gerrit.Label.COMMIT_QUEUE: cq_label,
                  }
                  retry_cl = retry_ci.to_gerrit_change_proto()
                  # Find path of appropriate project in local checkout, then set labels.
                  with self.m.context(cwd=workspace_path):
                    project_info = self.m.repo.project_info(retry_cl.project)
                    repository_path = self.m.path.join(workspace_path,
                                                       project_info.path)
                    with self.m.context(
                        cwd=self.m.path.abs_to_path(repository_path)):
                      self.m.gerrit.set_change_labels_remote(
                          retry_cl,
                          labels,
                      )
                if retry_cl_is_passed:
                  cls_to_abandon = [cl for cl in open_ci \
                      if cl.created < retry_ci.created]
                  if cls_to_abandon:
                    with self.m.step.nest("abandon CLs before passed CQ+1 CL"):
                      _abandon_cls(self.m, cls_to_abandon, retry_ci, \
                          outdated_cls_policy, self.retry_only_run)
      if not self.retry_only_run:
        assert ebuilds_by_pinfo is not None
        _create_uprev_cls(self.m, policy, ebuilds_by_pinfo, topic, open_changes,
                          existing_cls)

  def rebase_cl(self, open_changes: List[GerritChange], change_id: str,
                workspace_path: str, topic: str):
    with self.m.step.nest("rebase CL {}".format(change_id)):
      retry_changes = [p for p in open_changes if p.change == change_id]
      assert len(retry_changes) == 1
      retry_change = retry_changes[0]
      # Extract Change-Id from commit message
      description = self.m.gerrit.get_change_description(retry_change)
      change_id = _extract_metadata(description, 'Change-Id: (.*)')
      existing_versions = _deserialize_versions(
          _extract_metadata(description, UPREV_VERSION_LABEL + ': (.*)'))
      ebuilds_by_pinfo = self.uprev_packages(workspace_path, existing_versions,
                                             topic, change_id)
      if not ebuilds_by_pinfo:
        raise StepFailure('The uprev had no file.')
      if len(ebuilds_by_pinfo.keys()) > 1:
        raise StepFailure(
            'The uprev requires multi-repo commit. Cannot be rebased. {}'
            .format(sorted(ebuilds_by_pinfo.keys())))

  def uprev_packages(self, workspace_path: str,
                     versions: List[UprevVersionedPackageRequest.GitRef],
                     topic: str, change_id: Optional[str] = None
                    ) -> Optional[EbuildsByPinfo]:
    """Try the uprev for the given packages. If successful, commit the uprev.

    Args:
      workspace_path: Workspace checkout path where the build is processed.
      versions: The versions to consider for an update.
      topic: Topic describing package. Defaults to package title.
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
    return self.commit_uprevs(workspace_path, versions, topic,
                              all_valid_responses, modified_package_names,
                              change_id=change_id)

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

  def commit_uprevs(self, workspace_path: str,
                    versions: List[UprevVersionedPackageRequest.GitRef],
                    topic: str,
                    uprev_packages_responses: List[UprevPackagesResponse],
                    modified_package_names: List[str],
                    change_id: Optional[str] = None):
    """Commit the uprevs on the local filesystem.

    Args:
      workspace_path: Workspace checkout path where the build is processed.
      versions: The versions to consider for an update.
      topic: Topic describing package. Defaults to package title.
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
      with self.m.context(cwd=workspace_path):
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
        root = workspace_path.join(info.path)
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
            'Cq-Cl-Tag: pupr:{topic}'.format(topic=topic),
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

  def _get_policy(self, tag: str) -> PolicyInfo:
    """Find the applicable policy for the trigger.

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


def _abandon_cls(api: RecipeApi, outdated_cls: List[PatchSet],
                 most_recent_merged_uprev: PatchSet,
                 outdated_cls_policy: OutdatedClsPolicy, retry_only_run: bool,
                 abandoned_cls: Optional[List[PatchSet]] = None):
  """Abandon uprev CLs according to the outdated_cls_policy.

  Args:
    api: See RunSteps documentation.
    outdated_cls: Open uprev CLs that are behind the most recent merge.
    most_recent_merged_uprev: The most recent merged uprev CL.
    outdated_cls_policy: Policy to follow when for CLs that are still open but
        behind a merge.
    retry_only_run: Whether this run only applies retries to existing CLs (i.e.
        does not create a new uprev CL).
    abandoned_cls: List of CLs which have been abandoned. This value is mutated
        by the function call.
  """
  for outdated_cl in outdated_cls:
    if outdated_cls_policy == OUTDATED_LEAVE_COMMENT and not retry_only_run:
      outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                  'PUpr has been set to remind you that it'
                                  ' likely should be abandoned.').format(
                                      most_recent_merged_uprev.display_url)
      api.gerrit.add_change_comment(outdated_cl.to_gerrit_change_proto(),
                                    outdated_comment_message)
    elif outdated_cls_policy == OUTDATED_ABANDON:
      outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                  'PUpr has been set to abandon.').format(
                                      most_recent_merged_uprev.display_url)
      api.gerrit.abandon_change(outdated_cl.to_gerrit_change_proto(),
                                message=outdated_comment_message)
      if abandoned_cls is not None:
        abandoned_cls.append(outdated_cl)


def _create_uprev_cls(api: RecipeApi, policy: BranchPolicy,
                      ebuilds_by_pinfo: EbuildsByPinfo, topic: str,
                      open_changes: List[GerritChange], existing_cls: bool):
  """Create appropriate CLs for the uprevs."""
  send_to_cq_policy = (
      policy.existing_cls_policy
      if existing_cls else policy.no_existing_cls_policy)

  with api.step.nest('generate CLs'):
    changes = []
    for info in sorted(ebuilds_by_pinfo.keys()):
      changes.append(
          api.gerrit.create_change(
              info.path,
              reviewers=[reviewer.email for reviewer in policy.reviewers],
              topic=topic,
          ))
    api.easy.set_properties_step(
        generated_cls=[MessageToDict(change) for change in changes])

  if changes:
    with api.step.nest('cq-depend generated CLs'):
      cq_depends = api.cros_cq_depends.get_mutual_cq_depend(changes)
      for change, cq_depend in zip(changes, cq_depends):
        with api.step.nest('set cq-depend for {} CL'.format(
            change.project)) as presentation:
          if not cq_depend:
            presentation.step_text = "empty Cq-Depend, skipping"
            continue
          description = api.gerrit.get_change_description(change)
          description = api.git_footers.edit_add_change_description(
              description, 'Cq-Depend', cq_depend)
          api.gerrit.set_change_description(change, description,
                                            amend_local=True)

  with api.step.nest('update CL labels'):
    for change in changes:
      # First post explanatory message.
      message_lines = [
          'Found {} open CL(s) for Gerrit topic {}:'.format(
              len(open_changes), topic),
          '\n'.join(map(api.gerrit.parse_gerrit_change_url, open_changes)),
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
        api.gerrit.abandon_change(change, message=message)
      else:
        api.gerrit.add_change_comment(change, message)

      # Then set labels.
      labels = {
          DRY_RUN: {
              api.gerrit.Label.BOT_COMMIT: 1,
              api.gerrit.Label.COMMIT_QUEUE: 1,
          },
          FULL_RUN: {
              api.gerrit.Label.BOT_COMMIT: 1,
              api.gerrit.Label.COMMIT_QUEUE: 2,
          },
          SUBMIT: {
              api.gerrit.Label.BOT_COMMIT: 1,
          },
      }.get(send_to_cq_policy)

      if labels is not None:
        api.gerrit.set_change_labels(change, labels)

    if send_to_cq_policy == SUBMIT:
      with api.step.nest('submit CL'):
        api.gerrit.submit_change(change)


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
          post_process.MustRun, 'determine branch.fetch gitiles file.'
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
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'determine branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield _with_infos(
      'branch-policies-multiple-triggers',
      api.properties(triggers=[trigger_prop] * 2),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'determine branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multiple-trigger-policies',
      api.properties(triggers=[trigger_prop, trigger_prop2]),
      _props(package_info=package_chrome,
             branch_policies=[branch_policy, _policy()]),
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-no-pattern',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[no_pattern_policy]),
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
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
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multi-ref',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.step_data(
          'determine branch.git ls-remote',
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
