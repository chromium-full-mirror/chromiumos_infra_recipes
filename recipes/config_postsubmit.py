# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run miscellaneous actions on project repos.

Runs on a schedule rather than as a triggered/CQ action, so there is some
latency between commits landing and this script executing its tasks.

For example, if a src/project repo has filtered public configs, there can be an
action to copy these public configs to a public repo.

Each action is a function that takes a list of config repos to operate on and
returns a list of repos to make commits to.
"""

from collections import OrderedDict
import dataclasses
import re

from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo


from google.protobuf import json_format
from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.config_postsubmit import ConfigPostsubmitProperties
from recipe_engine import post_process
from recipe_engine import recipe_api

DEPS = [
    'depot_tools/gitiles',
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_scaling',
    'cros_source',
    'easy',
    'failures',
    'future_utils',
    'gerrit',
    'git',
    'git_txn',
    'repo',
    'src_state',
    'workspace_util',
]


PROPERTIES = ConfigPostsubmitProperties


@dataclasses.dataclass(frozen=True)
class CommitInfo:
  """Represents a commit that should be made as the result of an action."""
  api: recipe_api.RecipeApi

  project_info: ProjectInfo

  # Commit message.
  message: str

  @property
  def android_host(self) -> bool:
    """True if the commit is to an Android Gerrit host."""
    return not self.project_info.remote in ("cros", "cros-internal")

  @property
  def workspace_path(self) -> recipe_api.Path:
    """Path to the root of the workspace."""
    return self.api.src_state.android_workspace_path if self.android_host else self.api.src_state.workspace_path

  @property
  def gerrit_host_url(self) -> str:
    """URL of the Gerrit host.

    For example 'https://chromium-review.googlesource.com.'
    """
    if self.project_info.remote == "cros":
      return "https://chromium-review.googlesource.com"

    if self.project_info.remote == "cros-internal":  #pragma: nocover
      return "https://chrome-internal-review.googlesource.com"

    return "https://googleplex-android-review.googlesource.com"


def _replicate_public_config(api, _properties, project_infos, dry_run):
  """Replicates any public configs in project repos into a public repo.

  Args:
    See notes on _ACTIONS.
  """
  del dry_run
  public_repo_path = api.context.cwd / 'src' / 'project_public'

  automation_id = 'config_postsubmit/replicate_public'
  message = \
    '''Update with publically filtered configs.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), automation_id)

  for project_info in project_infos:
    with api.step.nest(project_info.name):
      public_config_path = (
          api.context.cwd / project_info.path / 'public_sw_build_config')
      api.path.mock_add_paths(public_config_path)
      if api.path.exists(public_config_path):
        # Parse the program and project name out of the project repo path. It is
        # expected that the project repo path has a format like
        # "src/project/<program>/<project>".
        #
        # The program and project names are then used to form the destination
        # path in the public repo.
        dirname, project_name = api.path.split(project_info.path)
        _, program_name = api.path.split(dirname)
        dest_path = public_repo_path.joinpath(program_name, project_name,
                                              'sw_build_config')

        # file.copytree will fail if the destination exists. Thus, remove
        # dest_path before doing the copy.
        api.file.rmtree('remove dest dir', dest_path)
        api.file.copytree('copy public config', public_config_path, dest_path)

  return [CommitInfo(api, api.repo.project_info(public_repo_path), message)]


def _update_device_stability(api, properties, _project_infos, dry_run):
  """Update the device stability configs in UFS.

  Uses the config_to_datastore script to do the update.

  Args:
    project_infos: ignored, but accepted. See notes on _ACTIONS.
  """
  del dry_run  # Unused.

  cwd = api.context.cwd
  config_internal = cwd / 'src/config-internal'

  config_to_ufs_datastore = (
      cwd / 'src/config/payload_utils/config_to_datastore.py')

  ufs_env = properties.ufs_env or 'prod'

  with api.context(config_internal),\
       api.step.nest('upload configs to ufs'):

    api.step('upload generated configs to UFS datastore', [
        config_to_ufs_datastore,
        '--debug',
        '--env',
        ufs_env,
    ])

  return []


def _update_android_config(api, properties, _project_infos, dry_run):
  """Downloads CrOS configs from snapshot builders and generates Android XMLs.

  For each of the snapshot_builders_to_monitor:
  1. Find the latest successful build.
  2. Download the config_protos.zip artifact.
  3. Unzip and find all the project config.jsonproto files.
  4. Use the cros_to_android.py script to convert them to Android XML config
     files.
  5. Return CommitInfos for the modified Android projects.

  The setup functions in this builder do not sync the Android source, so this
  function inits and syncs the relevant projects so that the project paths
  returned in the CommitInfos exist.

  Args:
    See notes on _ACTIONS. _project_infos is currently unused by this action.
  """
  del dry_run

  android_manifest = api.src_state.android_internal_manifest
  api.file.ensure_directory("ensure android workspace path",
                            api.src_state.android_workspace_path)
  with api.context(cwd=api.src_state.android_workspace_path):
    api.repo.init(android_manifest.url, manifest_depth=1)

  commit_infos = []

  for builder_name in properties.snapshot_builders_to_monitor:
    with api.step.nest(f"Process builder {builder_name}"):
      builds = api.buildbucket.search(
          builds_service_pb2.BuildPredicate(
              builder=builder_common_pb2.BuilderID(
                  project="chromeos",
                  bucket="postsubmit",
                  builder=builder_name,
              ),
              tags=api.buildbucket.tags(relevance="relevant"),
              status=common_pb2.SUCCESS,
          ),
          fields=["id", "output.properties"],
          limit=1,
          step_name=f"Find latest successful build for {builder_name}",
      )

      if not builds:
        api.step.active_result.presentation.step_text = (
            "No successful build found")
        continue

      build = builds[0]
      output_props = json_format.MessageToDict(build.output.properties)

      artifact_base_link = output_props.get("artifact_link")
      artifacts_info = output_props.get("artifacts",
                                        {}).get("files_by_artifact", {})
      if "config_protos.zip" not in artifacts_info.get("CHROMEOS_CONFIG", []):
        api.step.active_result.presentation.step_text = (
            "No config_protos.zip found")
        continue

      gs_path = f"{artifact_base_link}/config_protos.zip"
      api.step.active_result.presentation.step_text = (
          f"Found artifact {gs_path} from build {build.id}")

      dl_dir = api.path.mkdtemp(f"download_{builder_name}")
      unzip_dir = api.path.mkdtemp(f"unzip_{builder_name}")
      zip_local_path = dl_dir / "config_protos.zip"

      api.gsutil.download_url(gs_path, dl_dir)
      api.step(
          "unzip config_protos.zip",
          ["unzip", "-q", zip_local_path, "-d", unzip_dir],
      )

      jsonproto_files = api.file.glob_paths(
          name="find jsonproto files",
          source=unzip_dir,
          pattern="**/config.jsonproto",
          test_data=[
              unzip_dir /
              ("example_program/chromeos-config-bsp-private-0.0.1/example_project/generated/config.jsonproto"
              ),
              unzip_dir /
              ("example_program/chromeos-config-bsp-private-0.0.1/program/example_program/generated/config.jsonproto"
              ),
          ],
      )

      xsd_schema_path = api.path.mkdtemp("xsd_schema") / "hal_config.xsd"
      xsd_bytes = api.gitiles.download_file(
          "https://googleplex-android.googlesource.com/device/google/desktop/common",
          "config/hal_config.xsd",
          step_test_data=lambda: api.gitiles.test_api.make_encoded_file("""
<xs:schema attributeFormDefault="unqualified" elementFormDefault="qualified" xmlns:xs="http://www.w3.org/2001/XMLSchema">
</xs:schema>
            """),
      )

      api.file.write_raw(
          "write hal_config.xsd",
          xsd_schema_path,
          xsd_bytes,
      )

      cros_to_android_script = (
          api.context.cwd / "src/config/payload_utils/cros_to_android.py")

      project_to_hal_xml_path = {}
      project_to_feature_xml_output_dir = {}
      project_to_media_profiles_output_dir = {}
      for jsonproto_path in jsonproto_files:
        # config.jsonproto paths end with patterns like
        # chromeos-config-bsp-private-0.0.1/<program>/generated/config.jsonproto.
        # Extract the project name with a regex.
        match = re.search(
            r"chromeos-config-bsp-private-[\d\.]+/([^/]+)/generated/config.jsonproto",
            str(jsonproto_path),
        )
        if not match:
          continue

        project_name = match.group(1)

        with api.step.nest(
            f"Process {project_name} from {api.path.basename(jsonproto_path)}"):
          output_xml_path = api.path.mkdtemp(
              "output_hal_xml") / "hal_config.xml"
          api.step(
              f"Run generate-hal-xml for {project_name}",
              [
                  cros_to_android_script,
                  "generate-hal-xml",
                  "-o",
                  output_xml_path,
                  "-x",
                  xsd_schema_path,
                  jsonproto_path,
              ],
          )

          project_to_hal_xml_path[project_name] = output_xml_path

          feature_xml_output_dir = api.path.mkdtemp("output_feature_xml")
          api.step(
              f"Run generate-feature-xml for {project_name}",
              [
                  cros_to_android_script,
                  "generate-feature-xml",
                  "-o",
                  feature_xml_output_dir,
                  jsonproto_path,
              ],
          )
          project_to_feature_xml_output_dir[project_name] = (
              feature_xml_output_dir)

          media_profiles_output_dir = api.path.mkdtemp("output_feature_xml")
          dtd_schema = cros_to_android_script.parent / "media_profiles.dtd"
          api.step(
              f"Run generate-media-profiles for {project_name}",
              [
                  cros_to_android_script,
                  "generate-media-profiles",
                  "-o",
                  media_profiles_output_dir,
                  "-d",
                  dtd_schema,
                  jsonproto_path,
              ],
          )
          project_to_media_profiles_output_dir[
              project_name] = media_profiles_output_dir

      commit_message = f'''Automatic config update.

- Generated by {api.buildbucket.build_url()}.

Flag: EXEMPT desktop only
'''

      with api.context(cwd=api.src_state.android_workspace_path):
        # All the XMLs translated from a given CrOS build ('example-snapshot')
        # are committed to the same Android repo
        # ('device/google/desktop/example'). In the future each project in the
        # CrOS build will get its own repo.
        program_name = builder_name.removesuffix('-snapshot')
        api.repo.sync(projects=[f'device/google/desktop/{program_name}'],
                      current_branch=True)

        program_path = api.context.cwd / f'device/google/desktop/{program_name}'
        for project, xml_path in project_to_hal_xml_path.items():
          final_xml_path = program_path / f'configs/hal_configs/{project}/hal_config.xml'
          api.file.ensure_directory("ensure HAL XML path",
                                    final_xml_path.parent)
          api.file.move(
              f'move HAL XML for {project}',
              xml_path,
              final_xml_path,
          )

        for project, feature_xml_output_dir in project_to_feature_xml_output_dir.items(
        ):
          api.file.copytree(f"copy feature XMLs for {project}",
                            feature_xml_output_dir,
                            program_path / 'configs/features' / project,
                            allow_override=True)

        for project, media_profiles_output_dir in project_to_media_profiles_output_dir.items(
        ):
          api.file.copytree(f"copy media profile XMLs for {project}",
                            media_profiles_output_dir,
                            program_path / 'configs/media_profiles',
                            allow_override=True)

        project_info_test_data = api.repo.test_api.project_infos_test_data([{
            'project': 'device/google/desktop/example_program',
            'path': 'device/google/desktop/example_program',
            'remote': 'goog',
        }])
        commit_infos.append(
            CommitInfo(
                api,
                api.repo.project_info(program_path,
                                      test_data=project_info_test_data),
                commit_message))

  return commit_infos


# A map of CL configurations -> their functions which run on config repos.
#
# Each action should take a RecipesApi and list of ProjectInfos as args and
# optionally return a list of CommitInfos. In addition, each action should take
# a dry_run arg, to control interaction with external services, e.g. committing
# directly to git instead of returning a CommitInfo.
_ACTIONS = OrderedDict([
    (PROPERTIES.REPLICATE_PUBLIC_CONFIG, _replicate_public_config),
    (PROPERTIES.COPY_TO_INTERNAL, _update_device_stability),
    (PROPERTIES.UPDATE_ANDROID_CONFIG, _update_android_config),
])


def _create_cl(
    api: recipe_api.RecipeApi,
    _properties: ConfigPostsubmitProperties,
    commit_info: CommitInfo,
    branch_name: str,
    cl_config: ConfigPostsubmitProperties.ActionCLConfig,
) -> None:
  """Creates a CL based on commit_info.

  Hashes the project's directory contents and embeds the hash as a tag in the
  commit message, then queries Gerrit to detect identical changes. If identical
  changes are found, skips creating the CL.

  Args:
    api: See RunSteps documentation.
    commit_info: A CommitInfo object describing how to create the
      commit.
    branch_name: Name of the branch to create the commit on.
    cl_config: CL parameters & configuration.
  """
  with api.context(
      cwd=commit_info.workspace_path /
      commit_info.project_info.path), api.step.nest("create CL") as create_step:
    if api.git.get_working_dir_diff_files():
      api.repo.start(branch_name, projects=[api.context.cwd])

      api.git.add([api.context.cwd])

      with api.step.nest("query for existing changes") as query_step:
        project_hash = api.file.compute_hash(
            f'compute hash of {commit_info.project_info.path}',
            paths=[api.context.cwd], base_path=api.context.cwd)

        existing_changes = api.gerrit.query_changes(
            commit_info.gerrit_host_url,
            query_params=[
                ('status', 'open'),
                ('hashtag', f'content-hash-{project_hash}'),
                ('owner', api.buildbucket.swarming_task_service_account),
            ],
        )
        if existing_changes:
          query_step.step_text = (
              f"Skipping CL creation for {commit_info.project_info.path}: Found existing open CL "
              f"with the same Content-Hash ({project_hash[:8]}...): "
              f"{api.gerrit.parse_gerrit_change_url(existing_changes[0])}")
          return

      api.git.commit(commit_info.message)

      if cl_config.skip_upload:
        create_step.step_text = "skip_upload set, no CL created."
        return

      change = api.gerrit.create_change(
          project=commit_info.project_info.path,
          reviewers=cl_config.reviewers,
          ccs=cl_config.ccs,
          hashtags=list(cl_config.hashtags) + [f'content-hash-{project_hash}'],
          topic=cl_config.topic,
          project_path=api.context.cwd,
      )
      if cl_config.send_to_cq:
        with api.step.nest('send to CQ'):
          labels = {
              Label.PRESUBMIT_READY: 1
          } if commit_info.android_host else {
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          }
          api.gerrit.set_change_labels_remote(change, labels)
      if cl_config.abandon:
        api.gerrit.abandon_change(change)


def RunSteps(api, properties):

  def _get_config_projects():
    """Returns a list of ProjectInfos for all config repos."""

    # load all the repos defined in the DLM config.
    all_program_configs = api.file.read_json(
        'reading DLM config', api.context.cwd /
        'infra/config/project_config/all_programs_config.json')

    names = set()
    for program in all_program_configs.get('programs', []):
      name = program.get('repo', {}).get('name')
      if name:
        names.add(name)

      for project in program.get('deviceProjects', []):
        name = project.get('repo', {}).get('name')
        if name:
          names.add(name)

    project_infos = api.repo.project_infos(
        regexes=['chromeos/program', 'chromeos/project'])

    # filter out any projects not defined in DLM to avoid problems with
    # cancelled/removed projects who's repos haven't been deleted yet.
    return [info for info in project_infos if info.name in names]

  with api.workspace_util.setup_workspace(default_main=True):
    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()

    with api.context(cwd=api.cros_source.workspace_path):

      with api.step.nest('find config repos'):
        config_projects = _get_config_projects()

      # One action failing should not block all later actions from
      # running. Thus, catch StepFailures from each action and raise them later.
      #
      # Note that an action failing should stop the CL from being created
      # (i.e. a failed action might create an invalid CL), and thus
      # api.step.defer_results cannot be used.

      step_failures = []
      for cl_config_type, action in _ACTIONS.items():
        cl_config = properties.cl_configs[PROPERTIES.ActionTypes.Name(
            cl_config_type)]
        # Use the name of the fn. to create step names, branch names, etc.
        action_name = action.__name__.strip('_')
        with api.step.nest('Do {} and create CL'.format(action_name)):
          try:
            commit_infos = action(api, properties, config_projects,
                                  dry_run=not cl_config.send_to_cq)
            for commit_info in commit_infos:
              _create_cl(api, properties, commit_info, action_name, cl_config)
          except recipe_api.StepFailure as e:
            step_failures.append(e)

      # return RawResult directly to set the markdown (only with luciexe)
      return result_pb2.RawResult(
          status=common_pb2.FAILURE if step_failures else common_pb2.SUCCESS,
          summary_markdown=api.failures.format_step_failures(
              step_failures=step_failures))


def GenTests(api):

  def default_properties(allowed_projects=None, allowed_programs=None,
                         abandon: bool = False, skip_upload: bool = False):
    if allowed_projects is None:
      allowed_projects = [{'repo_name': 'chromeos/project/galaxy/milkyway'}]

    if allowed_programs is None:
      allowed_programs = [{'repo_name': 'chromeos/program/galaxy'}]

    aclc = PROPERTIES.ActionCLConfig(
        reviewers=['test1@google.com'],
        ccs=['test2@google.com',
             'test3@google.com'], topic='test topic', hashtags=['ht1', 'ht2'],
        send_to_cq=True, abandon=abandon, skip_upload=skip_upload)
    return api.properties(
        PROPERTIES(
            cl_configs={
                'REGENERATE_SUITE_SCHEDULER': aclc,
                'FLATTEN_CONFIGS': aclc,
                'COPY_TO_INTERNAL': aclc,
                'REPLICATE_PUBLIC_CONFIG': aclc,
                'REGENERATE_TEST_PLAN': aclc,
            },
            allowed_programs=allowed_programs,
            allowed_projects=allowed_projects,
            snapshot_builders_to_monitor=['example-snapshot'],
        ))

  def config_dlm_step_data(api):
    return api.step_data(
        'find config repos.reading DLM config',
        api.file.read_json({
            'programs': [
                {
                    'repo': {
                        'name': 'chromeos/program/galaxy',
                    },
                    'deviceProjects': [{
                        'repo': {
                            'name': 'chromeos/project/galaxy/milkyway'
                        }
                    },]
                },
                {
                    'repo': {
                        'name': 'chromeos/program/otherprogram',
                    },
                },
            ]
        }),
    )

  def config_repos_step_data(api):
    """Returns StepData for the find config repos call."""
    return api.step_data(
        'find config repos.repo forall', stdout=api.raw_io.output_text(
            '\n'.join(
                '{}|{}|cros|refs/heads/main|refs/heads/main'.format(name, path)
                for name, path in [
                    ('chromeos/project/galaxy/milkyway',
                     'src/project/galaxy/milkyway'),
                    ('chromeos/program/galaxy', 'src/program/galaxy'),
                    ('chromeos/program/otherprogram',
                     'src/program/otherprogram'),
                ]),
        ))

  def snapshot_build_step_data(api, include_artifacts=True):
    output = build_pb2.Build.Output()
    output.properties['artifact_link'] = (
        'gs://chromeos-image-archive/example-snapshot/R123-45678.0.0-123')
    if include_artifacts:
      output.properties['artifacts'] = {
          'files_by_artifact': {
              'CHROMEOS_CONFIG': ['config.yaml', 'config_protos.zip'],
          }
      }
    return api.buildbucket.simulated_search_results(
        [build_pb2.Build(
            id=123,
            status='SUCCESS',
            output=output,
        )],
        step_name='Do update_android_config and create CL.Process builder example-snapshot.Find latest successful build for example-snapshot',
    )

  def existing_changes_step_data(api, action, host_url, changes=None):
    return api.gerrit.set_query_changes_response(
        f"Do {action.__name__.strip('_')} and create CL.create CL.query for existing changes",
        host_url=host_url,
        changes=changes or [],
    )

  yield api.test(
      'basic',
      default_properties(),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      api.git.diff_check(True),
      existing_changes_step_data(api, action=_replicate_public_config, host_url="https://chromium-review.googlesource.com",),
      existing_changes_step_data(api, action=_update_android_config, host_url="https://googleplex-android-review.googlesource.com",),
      api.post_process(
          post_process.StepCommandContains,
          'Do replicate_public_config and create CL' \
              '.chromeos/project/galaxy/milkyway'    \
              '.copy public config',
          [
              'copytree',
              '[CLEANUP]/chromiumos_workspace/src/' \
                  'project/galaxy/milkyway/public_sw_build_config',
              '[CLEANUP]/chromiumos_workspace/src/' \
                'project_public/galaxy/milkyway/sw_build_config',
          ],
      ),
      api.post_check(post_process.DoesNotRunRE, r'.*\.abandon CL.*'),
  )

  yield api.test(
      'duplicate-android-cl-found',
      default_properties(),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      api.git.diff_check(True),
      existing_changes_step_data(
          api,
          action=_replicate_public_config,
          host_url="https://chromium-review.googlesource.com",
      ),
      existing_changes_step_data(
          api, action=_update_android_config,
          host_url="https://googleplex-android-review.googlesource.com",
          changes=[{
              '_number': 123,
              'project': 'example_repo',
          }]),
      api.post_process(
          post_process.StepTextContains,
          'Do update_android_config and create CL.create CL.query for existing changes.query https://googleplex-android-review.googlesource.com',
          ['found 1 matching CL'],
      ),
      api.post_check(
          post_process.DoesNotRunRE,
          r'Do update_android_config and create CL.create CL.create gerrit change for .*\.git_cl upload'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'failed_actions',
      default_properties(),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      api.step_data(
          'Do replicate_public_config and create CL' \
              '.chromeos/project/galaxy/milkyway'    \
              '.copy public config',
          retcode=1),
      api.post_process(post_process.DoesNotRunRE, 'git commit'),
      api.post_process(
          post_process.SummaryMarkdown,
          '1 step failed:\n\n\n- Infra Failure: '              \
               "Step('Do replicate_public_config and create CL" \
                   '.chromeos/project/galaxy/milkyway'          \
                   ".copy public config') (retcode: 1)\n"
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'abandon-cl',
      default_properties(abandon=True),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      existing_changes_step_data(
          api,
          action=_replicate_public_config,
          host_url="https://chromium-review.googlesource.com",
      ),
      api.post_check(post_process.MustRunRE,
                     r'Do \w* and create CL.create CL.abandon CL 1'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'update_device_stability-basic',
      default_properties(),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      api.post_process(
          post_process.MustRun,
          'Do update_device_stability and create CL'
          '.upload configs to ufs'
          '.upload generated configs to UFS datastore',
      ),
  )

  yield api.test(
      'no snapshot builders found',
      default_properties(),
      config_repos_step_data(api),
      api.buildbucket.simulated_search_results(
          [],
          step_name='Do update_android_config and create CL.Process builder example-snapshot.Find latest successful build for example-snapshot',
      ),
      config_dlm_step_data(api),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no config_protos.zip found',
      default_properties(),
      config_repos_step_data(api),
      snapshot_build_step_data(api, include_artifacts=False),
      config_dlm_step_data(api),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'skip upload',
      default_properties(skip_upload=True),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      existing_changes_step_data(
          api,
          action=_replicate_public_config,
          host_url="https://chromium-review.googlesource.com",
      ),
      api.post_process(post_process.DoesNotRunRE, r'.*git_cl upload'),
      api.post_process(post_process.DropExpectation),
  )
