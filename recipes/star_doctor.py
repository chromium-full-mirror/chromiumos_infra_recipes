# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

import base64
import functools
import json
from typing import Generator
from typing import List
from typing import Optional
from typing import Set

from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.gerrit.api import LabelConstraint
from RECIPE_MODULES.chromeos.gerrit.api import LabelConstraintKind
from google.protobuf.text_format import MessageToString

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.star_doctor import RemoteConfigFile
from PB.recipes.chromeos.star_doctor import StarDoctorProperties
from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import StepTestData
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/depot_tools',
    'depot_tools/gsutil',
    'cros_schedule',
    'deferrals',
    'gerrit',
    'git',
    'git_cl',
    'gitiles',
]


CI_PROD_SERVICE_ACCOUNT = 'chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com'
INTERNAL_HOST_DOMAIN = 'chrome-internal.googlesource.com'
EXTERNAL_HOST_DOMAIN = 'chromium.googlesource.com'
INTERNAL_REVIEW_HOST = 'https://chrome-internal-review.googlesource.com'
EXTERNAL_REVIEW_HOST = 'https://chromium-review.googlesource.com'
STARDOCTOR_TOPIC = 'StarDoctor'
CONFIG_UPDATE_HASHTAG = 'config-update'
TIMELINE_FILENAME = 'release/timeline_configuration.json'

PROPERTIES = StarDoctorProperties


class RepoProject():
  """A repo project that lives on one of ChromeOS's Gerrit instances.

  Attributes:
    name: str, the name of the project, as one might see in a manifest file:
      for example, 'chromeos/infra/config'.
    labels_for_upload: dict[Label, int], the Gerrit labels/values that should
      be attached to any CL on this project at upload-time for the CL to be
      submitted.
    checkout_path: Optional[Path], where on the local filesystem this project
      has been checked out. None if not yet cloned.
  """

  def __init__(self, name: str, is_internal: bool, has_verified_label: bool):
    """A repo project that lives on one of ChromeOS's Gerrit instances.

    Args:
      name: the name of the project, as one might see in a manifest file:
        for example, 'chromeos/infra/config'.
      is_internal: true if the project exists on CrOS's internal gerrit
        server, and not on the public gerrit server.
      has_verified_label: true if the project is configured on Gerrit to
        require a VERIFIED label for CL submission.
    """
    self.name = name
    self._is_internal = is_internal
    self.labels_for_upload = {
        Label.BOT_COMMIT: 1,
        Label.COMMIT_QUEUE: 2,
    }
    if has_verified_label:
      self.labels_for_upload[Label.VERIFIED] = 1
    self.checkout_path = None

  @property
  def host_domain(self) -> str:
    """The domain on which this project is hosted, without https:// prefix."""
    return INTERNAL_HOST_DOMAIN if self._is_internal else EXTERNAL_HOST_DOMAIN

  @property
  def host(self) -> str:
    """The URL on which this project is hosted."""
    return 'https://{}'.format(self.host_domain)

  @property
  def review_host(self) -> str:
    """The URL on which this project is reviewed."""
    return INTERNAL_REVIEW_HOST if self._is_internal else EXTERNAL_REVIEW_HOST

  @property
  def url(self) -> str:
    """The full URL to this project."""
    return '{}/{}'.format(self.host, self.name)

  def shallow_clone(self, api: RecipeApi, checkout_path: Optional[Path] = None,
                    **kwargs) -> None:
    """Shallow clone this project in a temporary directory.

    Args:
      api: The recipe modules API.
      checkout_path: If set, the directory to clone into.
      kwargs: Any other keyword arguments to pass into api.git.clone.
    """
    self.checkout_path = checkout_path or api.path.mkdtemp()
    api.git.clone(self.url, target_path=self.checkout_path, depth=1, **kwargs)

  def upload_changes(self, api: RecipeApi,
                     irrelevant_files: Optional[Set[str]] = None) -> None:
    """Commit and push changed files in this project.

    Args:
      api: The recipe modules API.
      irrelevant_files: Files that alone, shouldn't trigger a
        commit.
    """
    self._abandon_stale_changes(api)

    pending_cls = self._get_pending_stardoctor_cls(api)
    if pending_cls:
      api.step.empty(
          'Not committing changes to %s due to pending StarDoctor CLs' %
          self.name, log_text=[
              api.gerrit.parse_gerrit_change_url(chg) for chg in pending_cls
          ])
      return

    irrelevant_files = irrelevant_files or set()
    commit_lines = [
        'Automatic config update',
        'Generated by StarDoctor, see {} for the recipe.'.format(
            api.buildbucket.build_url()),
        'BUG=None\nTEST=regenerated configs',
    ]
    commit_msg = '\n\n'.join(commit_lines)
    step_name = 'committing to {}'.format(self.name)

    with api.step.nest(step_name) as presentation:
      with api.context(cwd=self.checkout_path):
        branch = api.git.current_branch()
        changed_files = api.git.get_working_dir_diff_files()

        # If there aren't leftover files when we subtract the irrelevant ones.
        if not set(changed_files) - irrelevant_files:
          presentation.step_text = 'no relevant files changed'
          return

        api.git.add(changed_files)
        api.git.commit(commit_msg)
        # Upload using git cl so that we can add topic and hashtags.
        # These are used to abandon unlanded changes later.
        change = api.gerrit.create_change(self.name, topic=STARDOCTOR_TOPIC,
                                          hashtags=[CONFIG_UPDATE_HASHTAG],
                                          ref=api.git.get_branch_ref(branch),
                                          project_path=self.checkout_path)
        api.gerrit.set_change_labels_remote(change, self.labels_for_upload)
        gerrit_change_url = api.git_cl.status(
            field='url', fast=True,
            step_test_data=functools.partial(api.raw_io.test_api.stream_output,
                                             'https://crrev.com/i/somenumber'))
        presentation.links['change uploaded'] = gerrit_change_url.decode()

  def _abandon_stale_changes(self, api: RecipeApi) -> None:
    """Abandon older changes that never landed.

    These are changes created by previous iterations of StarDoctor, which did
    not merge for some reason.

    Args:
      api: The recipe modules API.
    """
    cq_unapproved_constraint = LabelConstraint(
        label=Label.COMMIT_QUEUE, kind=LabelConstraintKind.UNAPPROVED)
    changes = self._get_stardoctor_cls(
        api, label_constraints=[cq_unapproved_constraint])
    for change in changes:
      api.gerrit.abandon_change(change)

  def _get_pending_stardoctor_cls(self, api: RecipeApi) -> List[GerritChange]:
    """Find any StarDoctor changes in the project still pending CQ verification.

    Args:
      api: The recipe modules API.

    Returns:
      Open StarDoctor CLs currently CQ-approved.
    """
    cq_approved_constraint = LabelConstraint(label=Label.COMMIT_QUEUE,
                                             kind=LabelConstraintKind.APPROVED)
    return self._get_stardoctor_cls(api,
                                    label_constraints=[cq_approved_constraint])

  def _get_stardoctor_cls(
      self, api: RecipeApi,
      label_constraints: Optional[List[LabelConstraint]] = None
  ) -> List[GerritChange]:
    """Find open StarDoctor CLs for this project matching certain constraints.

    Args:
      api: The recipe modules API.
      label_constraints: Constraints to apply to the query regarding Gerrit
        labels.

    Returns:
      Open StarDoctor CLs meeting the constraints.
    """
    return api.gerrit.query_changes(self.review_host, [
        ('project', self.name),
        ('owner', CI_PROD_SERVICE_ACCOUNT),
        ('topic', STARDOCTOR_TOPIC),
        ('hashtag', CONFIG_UPDATE_HASHTAG),
        ('status', 'open'),
    ], label_constraints=label_constraints)


INFRA_CONFIG = RepoProject('chromeos/infra/config', True, False)
CONFIG_INTERNAL = RepoProject('chromeos/config-internal', True, True)
SUITE_SCHEDULER = RepoProject('chromiumos/infra/suite_scheduler', False, True)
PUBLIC_CONFIG = RepoProject('chromiumos/config', False, True)


def RunSteps(api: RecipeApi, properties: StarDoctorProperties) -> None:
  with api.deferrals.raise_exceptions_at_end():
    with api.step.nest('set up'):
      _validate_properties(api, properties)
      _clone_repos(api)
    remote_config_files = _get_remote_config_files(properties)

    with api.step.nest('generate binary config'):
      _copy_remote_configs(api, remote_config_files)
      _fetch_and_write_chromiumos_schedule(api)
      _fetch_and_write_keyset_config(api)
      _update_release_time(api)
      with api.deferrals.defer_exceptions():
        _regenerate_configs(api)
      _copy_susch_configs(api)

    irrelevant_files = set()
    irrelevant_files.add(TIMELINE_FILENAME)
    _upload_all_changes(api, properties, irrelevant_files)


def _clone_repos(api: RecipeApi) -> None:
  """Shallow clone any necessary repo projects.

  Args:
    api: The recipe modules API.
  """
  INFRA_CONFIG.shallow_clone(api)
  SUITE_SCHEDULER.shallow_clone(api)
  CONFIG_INTERNAL.shallow_clone(api)
  # We need the config dir to exist in the `config` directory next to
  # config-internal for the symlinks in config-internal to work.
  config_dir = api.path.abspath(
      api.path.dirname(CONFIG_INTERNAL.checkout_path).join('config/'))
  api.step('create {}'.format(config_dir), ['mkdir', config_dir])
  PUBLIC_CONFIG.shallow_clone(api, checkout_path=config_dir)


def _validate_properties(api: RecipeApi, props: StarDoctorProperties) -> None:
  """Check that the input properties don't contain any contradictions."""
  with api.step.nest('validate properties'):
    if props.remote_config_files and (props.ge_bucket or props.branches):
      raise StepFailure(
          'ge_bucket and branches cannot be set if remote_config_files is set.')


def _get_remote_config_files(properties: StarDoctorProperties
                            ) -> List[RemoteConfigFile]:
  """Determine remote config files based on input properties.

  If properties.remote_config_files is not specified, build them based on the
  ge_bucket and branches properties. Note that if remote_config_files is
  specified, ge_bucket and branches should not be.

  Args:
    properties: Input properties to the recipe.

  Returns:
    A list of config files to download from Google Storage.

  Raises:
    StepFailure: If input properties specify remote_config_files and either
      ge_bucket or branches.
  """
  remote_config_files = properties.remote_config_files
  if not remote_config_files:
    remote_config_files.add(
        bucket_name=properties.ge_bucket,
        object_name='build_config.ToT.json',
        dest_path='release/ge_jsons/build_config.ToT.json',
    )
    for branch in properties.branches:
      branched_config = 'build_config.release-{}.json'.format(branch)
      remote_config_files.add(
          bucket_name=properties.ge_bucket,
          object_name=branched_config,
          dest_path='release/ge_jsons/{}'.format(branched_config),
      )
  return remote_config_files


def _copy_remote_configs(api: RecipeApi,
                         remote_config_files: List[RemoteConfigFile]) -> None:
  """Download the specified files from gsutil.

  Args:
    api: The recipe modules API.
    remote_config_files: config files to download from Google Storage.
  """
  with api.step.nest('copy remote configs'):
    for remote_config_file in remote_config_files:
      dest_path = api.path.join(INFRA_CONFIG.checkout_path,
                                remote_config_file.dest_path)
      api.gsutil.download(
          remote_config_file.bucket_name, remote_config_file.object_name,
          dest_path, name='download {}/{}'.format(
              remote_config_file.bucket_name,
              remote_config_file.object_name,
          ))


def _fetch_and_write_chromiumos_schedule(api: RecipeApi) -> None:
  """Read the release schedule from Cr-, and write it to infra/config."""
  with api.step.nest('fetch chromiumos schedule'):
    # Stay 10 milestones ahead.
    schedule_fname = api.path.join(INFRA_CONFIG.checkout_path,
                                   'release/schedule/schedule.textproto')
    last_mstone = api.cros_schedule.get_last_branched_mstone_n()
    fetch_n = last_mstone - 70 + 10
    mstones = api.cros_schedule.json_to_proto(
        api.cros_schedule.fetch_chromiumdash_schedule(start_mstone=70,
                                                      fetch_n=fetch_n))
    api.file.write_text('write textproto', schedule_fname,
                        MessageToString(mstones))


def _fetch_and_write_keyset_config(api: RecipeApi) -> None:
  """Read release keys from platform, and write it to infra/config."""
  with api.step.nest('fetch and write keyset configuration'):
    keyset_json = api.gitiles.get_file(
        INTERNAL_HOST_DOMAIN, 'chromeos/platform/release-keys',
        'generated/keyset.json', public=False,
        test_output_data=base64.b64encode(b'{"abc": 123}'))
    # Ensure it's json after all, then write.
    validated_keys = json.dumps(
        json.loads(keyset_json), sort_keys=True, indent=2)
    keyset_fname = api.path.join(INFRA_CONFIG.checkout_path,
                                 'release/signing/keyset.json')
    api.file.write_text('write keyset json', keyset_fname, validated_keys)


def _update_release_time(api: RecipeApi) -> None:
  """Update the infra/config/releases/timeline_configuration.json time field."""
  tl_cfg_fpath = api.path.join(INFRA_CONFIG.checkout_path, TIMELINE_FILENAME)
  with api.step.nest('update configured release time'):
    step_result = api.json.read(
        'read json', tl_cfg_fpath, step_test_data=lambda: api.json.test_api.
        output({'time': '2021-04-06T16:00:40Z'}))
    tl_cfg = step_result.json.output
    tl_cfg['time'] = api.time.utcnow().strftime('%FT%TZ')
    api.file.write_text('write release channel timeline configuration',
                        tl_cfg_fpath, json.dumps(tl_cfg, indent=2))


def _regenerate_configs(api: RecipeApi) -> None:
  """Runs the generate scripts in infra/config and src/config-internal."""
  # We need lucicfg from depot_tools.
  with api.depot_tools.on_path():
    # NOTE: The following generate scripts each obtain their own copy of protoc.
    with api.context(cwd=INFRA_CONFIG.checkout_path):
      # NOTE: we won't validate resource definitions for automated updates.
      api.step('regenerate configs',
               ['./regenerate_configs.py', '-b', '--no-check-resources'])
    with api.context(cwd=CONFIG_INTERNAL.checkout_path):
      api.step('regenerate test configs', ['./board_config/generate', '-b'],
               timeout=3 * 60)
      api.step('regenerate test exoneration configs',
               ['./test/exoneration/generate', '-b'], timeout=3 * 60)
      api.step(
          'regenerate suite scheduler configs',
          ['/bin/bash', 'test/suite_scheduler/regenerate_configs.sh', '-b'],
          timeout=3 * 60)


def _copy_susch_configs(api: RecipeApi) -> None:
  """Copy all config files from internal config to the suite_scheduler repo.

  Args:
    api: The recipe modules API.
  """
  with api.step.nest('copy suite scheduler configs'):
    orig_dir = api.path.join(CONFIG_INTERNAL.checkout_path, 'test',
                             'suite_scheduler', 'generated')
    dest_dir = api.path.join(SUITE_SCHEDULER.checkout_path, 'generated_configs')
    api.file.copy('lab_config.ini', api.path.join(orig_dir, 'lab_config.ini'),
                  dest_dir)
    api.file.copy('suite_scheduler.ini',
                  api.path.join(orig_dir, 'suite_scheduler.ini'), dest_dir)
    api.file.copy('lab_config.cfg', api.path.join(orig_dir, 'lab_config.cfg'),
                  dest_dir)
    api.file.copy('suite_scheduler.cfg',
                  api.path.join(orig_dir, 'suite_scheduler.cfg'), dest_dir)


def _upload_all_changes(api: RecipeApi, properties: StarDoctorProperties,
                        irrelevant_files: Optional[Set[str]] = None) -> None:
  """Commit and push changed files in all projects.

  Args:
    api: The recipe modules API.
    properties: A proto containing input properties.
    irrelevant_files: Files that alone, shouldn't trigger a commit.
  """
  with api.step.nest('commit changes') as presentation:
    if not properties.commit_changes:
      presentation.step_text = 'not configured to commit changes'
      return

    for project in (INFRA_CONFIG, SUITE_SCHEDULER, CONFIG_INTERNAL):
      with api.step.nest(project.name):
        project.upload_changes(api, irrelevant_files)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def _set_gerrit_query_changes_responses(
      projects_with_pending_changes: Optional[List[RepoProject]] = None
  ) -> StepTestData:
    """Set test data for gerrit.query_changes steps, with Gerrit labels.

    Args:
      projects_with_pending_changes: Names of projects where the returned
        should be listed as currently CQ-approved.

    Returns:
      Combined step test data (see StepTestData.__add__ for details).
    """
    if projects_with_pending_changes is None:
      projects_with_pending_changes = []
    test_datas = []
    for project in (INFRA_CONFIG, CONFIG_INTERNAL, SUITE_SCHEDULER):
      for iteration in (1, 2):
        changes_json = [{
            '_number': 12345,
            'project': project.name,
            'labels': {
                'Commit-Queue': {},
            }
        }]
        if project in projects_with_pending_changes:
          changes_json[0]['labels']['Commit-Queue'] = {
              'approved': {
                  '_account_id': 1337
              }
          }
        test_datas.append(
            api.gerrit.set_query_changes_response(
                '.'.join(['commit changes', project.name]), changes_json,
                project.review_host, iteration=iteration))
    return sum(test_datas[1:], test_datas[0])

  yield api.test(
      'dont-commit',
      api.time.seed(1613694623.0),
      api.properties(commit_changes=False),
  )

  yield api.test(
      'full',
      api.time.seed(1613694623.0),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']),
      _set_gerrit_query_changes_responses(),
  )

  yield api.test(
      'skip-pending-project', api.time.seed(1613694623.0),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']),
      _set_gerrit_query_changes_responses(
          projects_with_pending_changes=[SUITE_SCHEDULER]),
      api.post_check(
          post_process.MustRun,
          'commit changes.chromiumos/infra/suite_scheduler.Not committing changes to chromiumos/infra/suite_scheduler due to pending StarDoctor CLs'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'commit changes.chromiumos/infra/suite_scheduler.committing to chromiumos/infra/suite_scheduler'
      ),
      api.post_check(
          post_process.MustRun,
          'commit changes.chromeos/config-internal.committing to chromeos/config-internal'
      ),
      api.post_check(
          post_process.MustRun,
          'commit changes.chromeos/infra/config.committing to chromeos/infra/config'
      ))

  yield api.test(
      'only-irrelevant',
      api.time.seed(1613694623.0),
      api.step_data(
          'commit changes.chromeos/infra/config.committing to chromeos/infra/config.git status',
          stdout=api.raw_io.output_text(
              ' M release/timeline_configuration.json')),
      _set_gerrit_query_changes_responses(),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']),
      api.post_check(
          post_process.DoesNotRun,
          'commit changes.committing to chromeos/infra/config.git commit'),
  )

  yield api.test(
      'old-and-new-properties-set',
      api.time.seed(1613694623.0),
      api.properties(
          StarDoctorProperties(
              ge_bucket='test_ge_bucket',
              branches=['R9000'],
              remote_config_files=[
                  RemoteConfigFile(
                      bucket_name='test_bucket',
                      object_name='test_object',
                      dest_path='ge/test_object',
                  )
              ],
          )),
      api.post_process(post_process.StepFailure, 'set up.validate properties'),
      api.post_process(post_process.ResultReasonRE,
                       ('.*ge_bucket and branches cannot be set if'
                        ' remote_config_files is set..*')),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'defer-failure',
      api.time.seed(1613694623.0),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']),
      api.step_data('generate binary config.regenerate configs', retcode=1),
      _set_gerrit_query_changes_responses(),
      api.post_check(post_process.StepSuccess,
                     'generate binary config.deferring exception until later'),
      api.post_check(post_process.StepSuccess,
                     'generate binary config.copy suite scheduler configs'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
