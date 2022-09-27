# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the PUpr generator.

PUpr is a general uprev pipeline that listens for package releases (via LUCI
Scheduler gitiles triggers), generates ebuild uprev CLs for those releases,
and tags the appropriate reviewers. Think of it as the CrOS autoroller.

See go/pupr and go/pupr-generator for rationale and design decisions.
"""
import json

import six
from google.protobuf.json_format import MessageToDict

from collections import defaultdict, namedtuple
import re
from six.moves.urllib import parse as urlparse

from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import BuildTarget
from PB.chromite.api.packages import UprevVersionedPackageRequest

# pylint: disable=unused-import
from PB.recipes.chromeos.generator import (
    SendToCqPolicy, DO_NOTHING, DRY_RUN, FULL_RUN, ABANDON, SUBMIT,
    OutdatedClsPolicy, OUTDATED_DO_NOTHING, OUTDATED_LEAVE_COMMENT,
    OUTDATED_ABANDON, RetryClPolicy, NO_RETRY, RETRY_LATEST_OR_LATEST_PINNED,
    RETRY_LATEST_PINNED, BranchPolicy, Reviewer, GeneratorProperties, RetryRef,
    GitilesFetchInfo)
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import (
    CronTrigger, GitilesTrigger, Trigger, WebUITrigger)
from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process

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
    'git_footers',
    'gitiles',
    'naming',
    'pupr',
    'repo',
    'src_state',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = GeneratorProperties

# The label written in the commit message to store versions information of
# upstream repositories given by gitiles trigger.
UPREV_VERSION_LABEL = 'Pupr-Upstream-Versions'


def py2_MessageToJson(obj):
  # TODO(b/217973414): Delete once we don't need to fix the separator spacing
  # between py2 and py3 MessageToJson and replace usages with MessageToJson.
  return json.dumps(
      MessageToDict(obj), separators=(',', ': '), indent=2, sort_keys=True)


def serializeVersions(versions):
  """ Serialize versions information.

  Args:
    versions (List[UprevVersionedPackageRequest.GitRef]): The versions to consider for an update.

  Returns:
    A JSON string that encodes the input.
  """

  # Keys sorted in the alphabetical order to make the results consistent between Python 2 and 3.
  o = [{
      'ref': v.ref,
      'repository': v.repository,
      'revision': v.revision,
  } for v in versions]
  return json.dumps(o)


def RunSteps(api, properties):
  api.cros_source.configure_builder(api.src_state.gitiles_commit,
                                    api.src_state.gerrit_changes)
  workspace_path = api.cros_source.workspace_path

  policies = list(properties.branch_policies)

  with api.step.nest('validate properties') as presentation:
    if ((not properties.HasField('package_info') and not properties.packages) or
        (properties.HasField('package_info') and properties.packages)):
      raise StepFailure(
          'must set exactly one of {package_info, non-empty packages}')

    # Retrieve version information from Gitiles API.
    if properties.HasField('gitiles_info'):
      if not (properties.gitiles_info.host and
              properties.gitiles_info.project and properties.gitiles_info.path):
        raise StepFailure('gitiles fetch requested with no fetch '
                          'infomation supplied')

    for policy in policies:
      if not policy.pattern:
        raise StepFailure('must specify pattern')
      if not policy.reviewers:
        raise StepFailure('need at least one reviewer')

      for reviewer in policy.reviewers:
        if not reviewer.email:
          raise StepFailure('must set reviewer email')

    presentation.step_text = 'all properties good'

  retry_only_run = False
  triggers = properties.triggers or api.scheduler.triggers
  with api.step.nest('validate triggers') as presentation:
    if not triggers:
      raise StepFailure('found no scheduler triggers')

    has_cron_trigger = False
    for trigger in triggers:
      if trigger.HasField('cron'):
        has_cron_trigger = True
        break
    if has_cron_trigger:
      retry_only_run = True
      triggers = [Trigger(gitiles=GitilesTrigger(ref=properties.retry_ref.ref))]
      presentation.step_text = 'has cron trigger, runnning in retry-only mode'
    else:
      for trigger in triggers:
        if not trigger.HasField('gitiles'):
          raise StepFailure('found non-gitiles trigger: %r' % trigger)

      presentation.step_text = 'found {} good triggers'.format(len(triggers))
      presentation.logs['list of triggers'] = map(py2_MessageToJson, triggers)

  if properties.HasField('package_info'):
    packages = [properties.package_info]
  else:
    packages = properties.packages
  cpv = [api.naming.get_package_title(package) for package in packages]

  with api.cros_source.checkout_overlays_context(snapshot_mount=True), \
      api.cros_sdk.cleanup_context():
    api.cros_source.ensure_synced_cache(manifest_branch_override='main')

    # If we see gitiles_info populated in the recipe properties, we will be
    # performing a fetch from the Gitiles API for the package's target uprev
    # version. This information will be used in branch determination and sent to
    # the uprev handler.
    gitiles_response = None

    # Check out the appropriate branch, and use the appropriate policy.
    # If gitiles_info is given to us then we will determine the branch based on
    # the information returned by the Gitiles API. Otherwise, use the gitles.ref
    # seen in the trigger.
    with api.step.nest('determine branch') as pres:
      trigger_policies = []
      for trigger in triggers:
        # Retrieve version information from Gitiles API.
        if properties.HasField('gitiles_info'):
          gitiles_response = api.gitiles.get_file(
              str(properties.gitiles_info.host),
              str(properties.gitiles_info.project),
              str(properties.gitiles_info.path), ref=str(trigger.gitiles.ref),
              test_output_data='MTIzLjQ1Ni43ODkuMAo=')
          if gitiles_response:
            gitiles_response = gitiles_response.strip()

        # If we we recieved a target version from Gitiles, override the tag
        # argument.
        tag = gitiles_response or trigger.gitiles.ref
        policy_info = _get_policy(api, policies, tag)
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
        pres.step_text = 'using {} {}'.format(policy_info.branch,
                                              policy_info.reference.hash)
        api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                        policy_info.branch)
      else:
        pres.step_text = 'using default branch'
    api.easy.set_properties_step(policy=MessageToDict(policy))

    base_topic_name = properties.topic or cpv[0]
    if api.cq.active or api.src_state.gerrit_changes:
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
      with api.step.nest('apply gerrit changes'):
        if api.src_state.gerrit_changes:
          api.cros_source.apply_gerrit_changes(api.src_state.gerrit_changes)
        with api.step.nest('update policy') as pres:
          user = api.buildbucket.build.created_by.replace('user:', '', 1)
          api.easy.set_properties_step(original_policy=MessageToDict(policy))
          del policy.reviewers[:]
          policy.reviewers.add().email = user
          policy.existing_cls_policy = ABANDON
          policy.no_existing_cls_policy = ABANDON
          policy.outdated_cls_policy = OUTDATED_DO_NOTHING
          policy.retry_cl_policy = NO_RETRY
          policy.topic = '{}-{}'.format('testing', policy.topic or
                                        base_topic_name)
          api.easy.set_properties_step(policy=MessageToDict(policy))

    if properties.init_sdk:
      with api.context(cwd=workspace_path):
        api.cros_sdk.create_chroot(use_image=False)

    Ebuilds = namedtuple('Ebuilds', 'path version commit_info')

    topic = policy.topic or base_topic_name
    no_existing_cls_policy = policy.no_existing_cls_policy
    outdated_cls_policy = policy.outdated_cls_policy
    retry_cl_policy = policy.retry_cl_policy or NO_RETRY

    if not retry_only_run:
      # If earlier we fetched for a target version through Gitiles, pass along
      # the retrieved value.
      versions = [
          UprevVersionedPackageRequest.GitRef(
              repository=urlparse.urlparse(trigger.gitiles.repo).path,
              ref=trigger.gitiles.ref, revision=(gitiles_response or
                                                 trigger.gitiles.revision))
          for trigger in triggers
      ]
      ebuilds_by_pinfo = _do_uprev(
          api, properties, workspace_path, versions, packages, cpv, topic,
          Ebuilds, allow_partial_uprev=properties.allow_partial_uprev)
      if ebuilds_by_pinfo is None:
        return

    pinfos_by_remote = defaultdict(list)
    if not retry_only_run:
      for info in sorted(ebuilds_by_pinfo.keys()):
        pinfos_by_remote[info.remote].append(info)
    else:
      pinfos_by_remote[properties.retry_ref.remote] = [
          api.repo.ProjectInfo(
              remote=properties.retry_ref.remote,
              name=properties.retry_ref.name,
              branch=properties.retry_ref.ref,
              rrev=properties.retry_ref.ref,
              path=properties.retry_ref.path,
          )
      ]

    with api.step.nest('find open uprev CLs'):
      open_changes = []
      for host, remote in (('chromium', 'cros'), ('chrome-internal',
                                                  'cros-internal')):
        with api.step.nest('find CLs from {} host'.format(host)):
          host_url = 'https://{}-review.googlesource.com'.format(host)
          for info in pinfos_by_remote[remote]:
            open_changes.extend(
                api.gerrit.query_changes(host_url,
                                         [('topic', topic),
                                          ('project', info.name),
                                          ('branch', info.branch_name),
                                          ('status', 'open')]))

    mrm = None  # Most recently merged uprev.
    if open_changes:
      with api.step.nest('examine outdated CLs'):
        for host, remote in (('chromium', 'cros'), ('chrome-internal',
                                                    'cros-internal')):
          with api.step.nest('merged CLs from {} host (within 30 days)'.format(
              host)) as presentation:
            host_url = 'https://{}-review.googlesource.com'.format(host)
            merged_changes = []
            for info in pinfos_by_remote[remote]:
              merged_changes.extend(
                  api.gerrit.query_changes(host_url,
                                           [('topic', topic),
                                            ('project', info.name),
                                            ('branch', info.branch_name),
                                            ('status', 'merged'),
                                            ('-age', '30d')]))

            if merged_changes:
              presentation.logs['merged CLs'] = [
                  api.gerrit.parse_gerrit_change_url(cl)
                  for cl in merged_changes
              ]

              # Must fetch to get submitted times from the "PatchSets", which
              # are really instances of ChangeInfo.
              merged_ci = api.gerrit.fetch_patch_sets(merged_changes)
              list.sort(merged_ci, key=lambda ci: ci.submitted, reverse=True)
              mrm = merged_ci[0] if merged_ci else None
              presentation.logs['most recent merged cl'] = [mrm.display_id]
            else:
              presentation.step_text = 'no merged CLs found'
              presentation.status = api.step.WARNING

    outdated_cls, abandoned_cls = [], []
    if mrm:
      open_ci = api.gerrit.fetch_patch_sets(open_changes)
      with api.step.nest('outdated CLs') as presentation:
        outdated_cls.extend(
            [ci for ci in open_ci if ci.created < mrm.submitted])
        presentation.logs['outdated CLs'] = [
            ci.display_id for ci in outdated_cls
        ]

    if outdated_cls:
      with api.step.nest('act on outdated CLs with policy: {}'.format(
          OutdatedClsPolicy.Name(outdated_cls_policy))) as pres:
        _abandon_cls(api, outdated_cls, mrm, outdated_cls_policy, \
            retry_only_run, abandoned_cls)

    existing_cls = open_changes and len(abandoned_cls) < len(open_changes)

    if retry_cl_policy != NO_RETRY:
      with api.step.nest('apply retry policy {}'.format(
          RetryClPolicy.Name(retry_cl_policy))) as presentation:
        if open_changes:
          open_ci = api.gerrit.fetch_patch_sets(open_changes,
                                                include_messages=True)
          # Filter out outdated CLs, sort by recency
          if mrm:
            open_ci = [ci for ci in open_ci if ci.created > mrm.submitted]
          open_ci = sorted(open_ci, key=lambda ci: ci.created, reverse=True)

          if not api.pupr.retries_frozen(open_ci):
            retry_ci, cq_label, message, retry_cl_is_passed = api.pupr.identify_retry(
                retry_cl_policy, no_existing_cls_policy, open_ci)
            presentation.step_text = message

            if retry_ci:
              with api.step.nest("retry CL {}".format(retry_ci.change_id)):
                labels = {
                    api.gerrit.Label.BOT_COMMIT: 1,
                    api.gerrit.Label.COMMIT_QUEUE: cq_label,
                }
                retry_cl = retry_ci.to_gerrit_change_proto()
                # Find path of appropriate project in local checkout, then set labels.
                with api.context(cwd=workspace_path):
                  project_info = api.repo.project_info(retry_cl.project)
                  repository_path = api.path.join(workspace_path,
                                                  project_info.path)
                  with api.context(cwd=api.path.abs_to_path(repository_path)):
                    api.gerrit.set_change_labels_remote(
                        retry_cl,
                        labels,
                    )
              if retry_cl_is_passed:
                cls_to_abandon = [cl for cl in open_ci \
                    if cl.created < retry_ci.created]
                if cls_to_abandon:
                  with api.step.nest("abandon CLs before passed CQ+1 CL"):
                    _abandon_cls(api, cls_to_abandon, retry_ci, \
                        outdated_cls_policy, retry_only_run)
    if not retry_only_run:
      _create_uprev_cls(api, policy, ebuilds_by_pinfo, topic, open_changes,
                        existing_cls)


def _get_policy(api, policies, tag):
  """Find the applicable policy for the trigger.

  The policy used is the first policy where policy.pattern matches the tag, and
  either:
  - the substitution result is the empty string (default branch, aka legacy), or
  - a remote reference is in manifest-internal for the substitution result.

  Args:
    policies (list(BranchPolicy): The package's branch policy.
    tag (string): Version information used to generate the branch name.
      (e.g. 123.456.789.0)

  Returns:
    (PolicyInfo) namedtuple with:
    - policy (BranchPolicy): The selected policy
    - branch (str): the branch to checkout.  Empty if there is no branch to
      checkout.
    - reference (git.Reference): the reference that matched, or None.
  """
  PolicyInfo = namedtuple('PolicyInfo', ['policy', 'branch', 'reference'])
  manifest = api.src_state.internal_manifest
  with api.context(cwd=manifest.path):
    for policy in policies:
      if re.match(policy.pattern, six.ensure_str(tag)):
        query = re.sub(policy.pattern, policy.repl, six.ensure_str(tag))
        if not query:
          return PolicyInfo(policy, '', None)
        refs = api.git.ls_remote([query])
        if len(refs) == 1:
          ref = refs[0]
          return PolicyInfo(policy, ref.ref.split('/')[-1], ref)
        if refs:
          raise StepFailure('multiple branches matched {}: {}'.format(
              query, ' '.join(x.ref for x in refs)))
        # If we found no references, this policy does not apply.

    raise StepFailure('No matching policy found for tag {}'.format(tag))


# TODO(dburger): deleted files should be at the end of the modified_ebuilds list
# to work correctly with api.git.diff_check.
def response_has_changes(api, response):
  """Returns whether the given `UprevPackagesResponse` contains changes."""
  for ebuild in response.modified_ebuilds:
    path = ebuild.path
    with api.context(cwd=api.path.abs_to_path(api.path.dirname(path))):
      if api.git.diff_check(path):
        return True
  return False


def _abandon_cls(api, outdated_cls, most_recent_merged_uprev,
                 outdated_cls_policy, retry_only_run, abandoned_cls=None):
  """Abandon uprev CLs according to the outdated_cls_policy.

  Args:
    api (RecipeApi): See RunSteps documentation.
    outdated_cls (list[PatchSet]): Open uprev CLs that are behind the most
        recent merge.
    most_recent_merged_uprev (PatchSet): The most recent merged uprev CL.
    outdated_cls_policy (OutdatedClsPolicy): Policy to follow when for CLs that
        are still open but behind a merge.
    retry_only_run (bool): Whether this run only applies retries to existing CLs
        (i.e. does not create a new uprev CL).
    abandoned_cls (list[PatchSet]): List of CLs which have been abandoned. This
        value is mutated by the function call.
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


def _do_uprev(api, properties, workspace_path, versions, packages, cpvs, topic,
              Ebuilds, allow_partial_uprev=False):
  """Try the uprev for the given package. If successful, commit the uprev.

  Args:
    properties (GeneratorProperties): Current properties for the recipe run.
    workspace_path (string): Workspace checkout path where the build is
      processed.
    versions (List[UpdateVersionedPackageRequest.GitRef]): The versions to consider for an update.
    triggers (scheduler.Trigger): Triggers which invoked the recipe.
    packages (List[chromiumos.PackageInfo]): Information describing the package.
    cpv (List[string]): Package title. Must be in a matching order to packages.
    topic (string): Topic describing package. Defaults to package title.
      can be same as cpv.
    Ebuilds (namedtuple): Contains path and version.
    allow_partial_uprev: Whether to continue operation when either of the packages
      has no modified files.

  Returns:
    (dict): ebuilds_by_pinfo. If None, pupr should return immediately.
  """
  assert len(packages) == len(cpvs)
  modified_package_names = []
  all_valid_responses = []
  for package, cpv in zip(packages, cpvs):
    with api.step.nest('try uprev {}'.format(cpv)) as presentation:
      request = UprevVersionedPackageRequest(
          chroot=api.cros_sdk.chroot,
          package_info=package,
          versions=versions,
          build_targets=properties.build_targets,
      )
      presentation.logs['request'] = str(request)
      response = api.cros_build_api.PackageService.UprevVersionedPackage(
          request, name='uprev versioned package')

      if not response.responses:
        presentation.step_text = 'no new versions for {}'.format(cpv)
        return None

      valid_responses = []
      with api.step.nest('verify updates'):
        # only act on files that are actually modified
        for uprev_resp in response.responses:
          if response_has_changes(api, uprev_resp):
            valid_responses.append(uprev_resp)

      if not valid_responses:
        presentation.step_text = (
            'skipping uprev for {}. no modified files'.format(cpv))
        if not allow_partial_uprev:
          return None
        presentation.logs['partial_uprev'] = [
            'no modified file for {}. continue because allow_partial_uprev=True'
            .format(cpv)
        ]
        continue
      all_valid_responses.extend(valid_responses)
      modified_package_names.append(package.package_name)

      presentation.logs['uprev versions'] = [
          response.version for response in valid_responses
      ]

  if not all_valid_responses:
    return None

  with api.step.nest('commit uprev'):
    # Flatten the list of modified files, and get the project info for them.
    modified_ebuilds = []
    for uprev_resp in all_valid_responses:
      modified_ebuilds.extend(
          Ebuilds(path=ebuild.path, version=uprev_resp.version,
                  commit_info=uprev_resp.additional_commit_info)
          for ebuild in uprev_resp.modified_ebuilds)
    with api.context(cwd=workspace_path):
      ebuilds_by_pinfo = defaultdict(list)
      for ebuild in modified_ebuilds:
        dirname = api.path.dirname(ebuild.path)
        info = api.repo.project_infos(projects=[dirname])[0]
        ebuilds_by_pinfo[info].append(ebuild)

      # Checkout git branches via repo so they track correctly.  Create them
      # by path instead of project name, because they may be checked out
      # multiple times.
      api.repo.start(
          'pupr',
          projects=[info.path for info in sorted(ebuilds_by_pinfo.keys())])

    # For each repository, make the CL.
    for info, ebuilds in sorted(ebuilds_by_pinfo.items()):
      name = api.path.basename(info.path)
      root = workspace_path.join(info.path)
      vers = ', '.join(sorted({e.version for e in ebuilds}))
      additional_commit_msg = ''
      additional_commit_info = [e.commit_info for e in ebuilds if e.commit_info]
      if additional_commit_info:
        additional_commit_msg = '\n'.join(sorted(
            set(additional_commit_info))) + '\n'
      commit_lines = [
          '{package_name}: Automatic uprev to {versions}.'.format(
              package_name=', '.join(modified_package_names), versions=vers),
          '',
          '{additional_msg}Generated by PUpr, see {build_url} for job details.'
          .format(additional_msg=additional_commit_msg,
                  build_url=api.buildbucket.build_url()),
          '',
          'BUG=None',
          'TEST=CQ',
          '',
          '{label}: {versions}'.format(label=UPREV_VERSION_LABEL,
                                       versions=serializeVersions(versions)),
          'Cq-Cl-Tag: pupr:{topic}'.format(topic=topic),
      ]
      if api.src_state.gerrit_changes:
        commit_lines.append('Cq-Depend: {}'.format(','.join(
            '{}:{}'.format(
                x.host.split('.', 1)[0].replace('-review', ''), x.change)
            for x in api.src_state.gerrit_changes)))
      commit_message = '\n'.join(commit_lines) + '\n'

      with api.step.nest('commit in {}'.format(name)), api.context(cwd=root):
        api.git.add([e.path for e in ebuilds])
        api.git.commit(commit_message)

  return ebuilds_by_pinfo


def _create_uprev_cls(api, policy, ebuilds_by_pinfo, topic, open_changes,
                      existing_cls):
  """Create appropriate CLs for the uprevs.
  """
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


def GenTests(api):

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

  def _with_infos(name, *args, **kwargs):
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
      api.test_util.test_build(
          revision=None, extra_changes=[],
          created_by='user:lamontjones@chromium.org').build)

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
      'multiple-packages',
      api.properties(triggers=[trigger_prop]),
      _props(
          packages=[
              package_chrome,
              PackageInfo(category='chromeos-base',
                          package_name='chromeos-lacros'),
          ],
          package_info=None,
          topic='chromeos-base/new-topic-name',
      ),
      api.git.diff_check(True),
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
          ['--topic', 'chromeos-base/new-topic-name']),
  )

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
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_OR_LATEST_PINNED'),
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
