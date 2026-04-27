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
import xml.etree.ElementTree as ET

from typing import Optional

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
    'build_internal/android_build',
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
    'deferrals',
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

  # The root of the workspace where the commit should be created.
  workspace_path: recipe_api.Path

  # Android host to upload the commit to. Should only be set for Android commits.
  android_host: Optional[str] = None

  @property
  def gerrit_host_url(self) -> str:
    """URL of the Gerrit host.

    For example 'https://chromium-review.googlesource.com.'
    """
    if self.project_info.remote == "cros":
      return "https://chromium-review.googlesource.com"

    if self.project_info.remote == "cros-internal":  #pragma: nocover
      return "https://chrome-internal-review.googlesource.com"

    return f"https://{self.android_host}-review.googlesource.com"


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

  return [
      CommitInfo(
          api,
          api.repo.project_info(
              public_repo_path,
              test_data='chromeos/project_public|src/project_public|cros|refs/heads/main|refs/heads/main'
          ),
          message,
          workspace_path=api.src_state.workspace_path,
      )
  ]


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

  host = properties.android_host or "googleplex-android"

  workspace_path = api.path.cleanup_dir / f"{host}_workspace"
  manifest_url = f"https://{host}.googlesource.com/platform/manifest"

  api.file.ensure_directory(f"ensure {host} workspace path", workspace_path)
  with api.context(cwd=workspace_path):
    api.repo.init(manifest_url, manifest_depth=1)

  commit_infos = []

  with api.deferrals.raise_exceptions_at_end():
    for builder_name in properties.snapshot_builders_to_monitor:
      with api.step.nest(
          f"Process builder {builder_name}"), api.deferrals.defer_exceptions():
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
            f"https://{host}.googlesource.com/device/google/desktop/common",
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
        project_to_feature_from_hal_xml_output_dir = {}
        project_to_media_profiles_output_dir = {}
        project_to_media_profiles_from_hal_output_dir = {}
        project_to_component_xml_output_dir = {}
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
              f"Process {project_name} from {api.path.basename(jsonproto_path)}"
          ):
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

            feature_from_hal_xml_output_dir = api.path.mkdtemp(
                "output_feature_from_hal_xml")
            api.step(
                f"Run generate-feature-xml from HAL for {project_name}",
                [
                    cros_to_android_script,
                    "generate-feature-xml",
                    "--from-hal-config",
                    "-o",
                    feature_from_hal_xml_output_dir,
                    jsonproto_path,
                ],
            )
            project_to_feature_from_hal_xml_output_dir[project_name] = (
                feature_from_hal_xml_output_dir)

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

            media_profiles_from_hal_output_dir = api.path.mkdtemp(
                "output_media_profiles_from_hal")
            api.step(
                f"Run generate-media-profiles from HAL for {project_name}",
                [
                    cros_to_android_script,
                    "generate-media-profiles",
                    "--from-hal-config",
                    "-o",
                    media_profiles_from_hal_output_dir,
                    "-d",
                    dtd_schema,
                    jsonproto_path,
                ],
            )
            project_to_media_profiles_from_hal_output_dir[project_name] = (
                media_profiles_from_hal_output_dir)

            component_xml_output_dir = api.path.mkdtemp("output_component_xml")
            api.step(
                f"Run generate-component-xmls for {project_name}",
                [
                    cros_to_android_script,
                    "generate-component-xmls",
                    "-o",
                    component_xml_output_dir,
                    jsonproto_path,
                ],
            )
            project_to_component_xml_output_dir[
                project_name] = component_xml_output_dir

        commit_message = f'''Automatic config update.

- Generated by {api.buildbucket.build_url()}.

Flag: EXEMPT desktop only
'''

        with api.context(cwd=workspace_path):
          # If the builder is in project_repo_snapshot_builders, then each
          # project repo gets its own commit. Otherwise all configs are committed
          # to the program repo.
          #
          # Note that the configs go to slightly different places depending on
          # whether the builder is in project_repo_snapshot_builders, so we need
          # fully separate logic. For example, hal_config.xml is in a
          # project-specific directory in the program repo.
          if builder_name in properties.project_repo_snapshot_builders:
            for project_name, hal_xml_path in project_to_hal_xml_path.items():
              repo_path_str = f'device/google/desktop/{project_name}'
              api.repo.sync(projects=[repo_path_str], current_branch=True,
                            step_name=f'repo sync {project_name}')

              project_path = api.context.cwd / repo_path_str
              final_xml_path = project_path / 'configs/hal_config.xml'
              api.file.ensure_directory("ensure HAL XML path",
                                        final_xml_path.parent)
              api.file.move(
                  f'move HAL XML for {project_name}',
                  hal_xml_path,
                  final_xml_path,
              )

              if project_name in project_to_feature_xml_output_dir:
                api.file.copytree(
                    f"copy feature XMLs for {project_name}",
                    project_to_feature_xml_output_dir[project_name],
                    project_path / 'configs/features' / project_name,
                    allow_override=True)

              if project_name in project_to_feature_from_hal_xml_output_dir:
                api.file.copytree(
                    f"copy feature from HAL XMLs for {project_name}",
                    project_to_feature_from_hal_xml_output_dir[project_name],
                    project_path / 'configs/features_from_hal',
                    allow_override=True)

              if project_name in project_to_media_profiles_output_dir:
                api.file.copytree(
                    f"copy media profile XMLs for {project_name}",
                    project_to_media_profiles_output_dir[project_name],
                    project_path / 'configs/media_profiles',
                    allow_override=True)

              if project_name in project_to_media_profiles_from_hal_output_dir:
                api.file.copytree(
                    f"copy media profile from HAL XMLs for {project_name}",
                    project_to_media_profiles_from_hal_output_dir[project_name],
                    project_path / 'configs/media_profiles_from_hal',
                    allow_override=True)

              if project_name in project_to_component_xml_output_dir:
                api.file.copytree(
                    f"copy component XMLs for {project_name}",
                    project_to_component_xml_output_dir[project_name],
                    project_path / 'configs/components', allow_override=True)

              project_info_test_data = api.repo.test_api.project_infos_test_data(
                  [{
                      'project': repo_path_str,
                      'path': repo_path_str,
                      'remote': 'goog',
                  }])
              commit_infos.append(
                  CommitInfo(
                      api,
                      api.repo.project_info(project_path,
                                            test_data=project_info_test_data),
                      commit_message,
                      android_host=host,
                      workspace_path=workspace_path,
                  ))
          else:
            program_name = builder_name.removesuffix('-snapshot')
            repo_path_str = f'device/google/desktop/{program_name}'
            api.repo.sync(projects=[repo_path_str], current_branch=True,
                          step_name=f'repo sync {repo_path_str}')

            program_path = api.context.cwd / repo_path_str
            if project_to_hal_xml_path:
              # Combine the hal_config.xmls from eacn project into one XML file,
              # because the Makefile is expecting a single XML file. Eventually
              # all projects should be migrated to project_repo_snapshot_builders
              # and this can be removed.
              #
              # The root of the first XML file is used as the root of the combined
              # file. All children of the root element of the other files are
              # appended to this root.
              # This assumes that all hal_config.xml files have the same root
              # element name.

              # Read the first XML file to establish the root of the combined file.
              projects = list(project_to_hal_xml_path.keys())
              first_project = projects[0]
              first_xml_path = project_to_hal_xml_path[first_project]
              first_xml_content = api.file.read_text(
                  f'read first hal_config.xml for {first_project}',
                  first_xml_path,
                  test_data='''<HalConfigurations><HalConfig><Identity><sku-id>1</sku-id><model>project-model</model></Identity></HalConfig></HalConfigurations>''',
              )
              root = ET.fromstring(first_xml_content)

              # Append the children of the root element of the other XML files.
              for project in projects[1:]:
                xml_path = project_to_hal_xml_path[project]
                xml_content = api.file.read_text(
                    f'read hal_config.xml for {project}', xml_path,
                    test_data='''<HalConfigurations><HalConfig><Identity><sku-id>1</sku-id><model>project-model</model></Identity></HalConfig></HalConfigurations>'''
                )
                other_root = ET.fromstring(xml_content)
                for child in other_root:
                  root.append(child)

              # The combined file is written to the program's config directory.
              final_xml_path = program_path / 'configs/hal_config.xml'
              api.file.ensure_directory("ensure HAL XML path",
                                        final_xml_path.parent)
              ET.indent(root, space='  ')
              combined_xml_content = ET.tostring(root, encoding='unicode')
              api.file.write_text(f'write combined HAL XML for {program_name}',
                                  final_xml_path, combined_xml_content)

            for project, feature_xml_output_dir in project_to_feature_xml_output_dir.items(
            ):
              api.file.copytree(f"copy feature XMLs for {project}",
                                feature_xml_output_dir,
                                program_path / 'configs/features' / project,
                                allow_override=True)

            for project, feature_from_hal_xml_output_dir in project_to_feature_from_hal_xml_output_dir.items(
            ):
              api.file.copytree(
                  f"copy feature from HAL XMLs for {project}",
                  feature_from_hal_xml_output_dir,
                  program_path / 'configs/features_from_hal' / project,
                  allow_override=True)

            for project, media_profiles_output_dir in project_to_media_profiles_output_dir.items(
            ):
              api.file.copytree(f"copy media profile XMLs for {project}",
                                media_profiles_output_dir,
                                program_path / 'configs/media_profiles',
                                allow_override=True)

            for project, media_profiles_from_hal_output_dir in project_to_media_profiles_from_hal_output_dir.items(
            ):
              api.file.copytree(
                  f"copy media profile from HAL XMLs for {project}",
                  media_profiles_from_hal_output_dir,
                  program_path / 'configs/media_profiles_from_hal' / project,
                  allow_override=True)

            for project, component_xml_output_dir in project_to_component_xml_output_dir.items(
            ):
              api.file.copytree(f"copy component XMLs for {project}",
                                component_xml_output_dir,
                                program_path / 'configs/components' / project,
                                allow_override=True)

            project_info_test_data = api.repo.test_api.project_infos_test_data(
                [{
                    'project': 'device/google/desktop/example_program',
                    'path': 'device/google/desktop/example_program',
                    'remote': 'goog',
                }])
            commit_infos.append(
                CommitInfo(
                    api,
                    api.repo.project_info(program_path,
                                          test_data=project_info_test_data),
                    commit_message,
                    android_host=host,
                    workspace_path=workspace_path,
                ))

  return commit_infos


def _update_component_ids_from_android(api, properties, _project_infos,
                                       dry_run):
  """Downloads component_ids.star from Android builds and commits them to CrOS.

  Args:
    See notes on _ACTIONS.
  """
  del dry_run
  mapping = properties.android_target_to_cros_path or {}
  if not mapping:
    api.step.active_result.presentation.step_text = 'No mapping provided'
    return []

  commit_infos = []
  branch = 'arsp-main'

  for target, cros_repo_path in mapping.items():
    with api.step.nest(f'Process {target}'):
      # Extract project name for artifact filename, assuming it's the part before the first hyphen.
      # Example: moonstone-trunk_staging-userdebug -> moonstone
      project_name = target.split('-')[0]
      artifact_filename = f'{project_name}-component_ids.star'

      dl_dir = api.path.mkdtemp(f'download_{target}')

      # Use download_from_api to fetch artifact.
      # We don't pass bid, so it finds the latest build.
      api.android_build.download_from_api(
          name=f'Download {artifact_filename}',
          path=dl_dir,
          target=target,
          branch=branch,
          filenames=[artifact_filename],
      )

      downloaded_file = dl_dir / artifact_filename

      project_path = api.cros_source.workspace_path / cros_repo_path
      final_path = project_path / 'android_component_ids.star'

      api.file.ensure_directory('ensure project path exists', project_path)
      api.file.copy(f'copy {artifact_filename}', downloaded_file, final_path)

      commit_message = f'''Update component_ids from Android.

- Generated by {api.buildbucket.build_url()}.
'''

      # We need ProjectInfo for CommitInfo.
      # Assuming it is a valid repo.
      project_info = api.repo.project_info(
          project_path,
          test_data='chromeos/project/program/project|src/project/program/project|cros|refs/heads/main|refs/heads/main'
      )

      commit_infos.append(
          CommitInfo(
              api,
              project_info,
              commit_message,
              workspace_path=api.src_state.workspace_path,
          ))

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
    (PROPERTIES.UPDATE_COMPONENT_IDS, _update_component_ids_from_android),
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
      commit_info.project_info.path), api.step.nest(
          f"Create CL for {commit_info.project_info.name}") as create_step:
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
      change_url = api.gerrit.parse_gerrit_change_url(change)
      create_step.links['Created CL'] = change_url
      if cl_config.send_to_cq:
        with api.step.nest('send to CQ'):
          labels = {
              Label.PRESUBMIT_READY: 1,
              Label.AUTOSUBMIT: 1,
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
                         abandon: bool = False, skip_upload: bool = False,
                         android_host: str = None,
                         snapshot_builders_to_monitor=None):
    if allowed_projects is None:
      allowed_projects = [{'repo_name': 'chromeos/project/galaxy/milkyway'}]

    if allowed_programs is None:
      allowed_programs = [{'repo_name': 'chromeos/program/galaxy'}]

    if snapshot_builders_to_monitor is None:
      snapshot_builders_to_monitor = ['example-snapshot']

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
                'UPDATE_ANDROID_CONFIG': aclc,
                'UPDATE_COMPONENT_IDS': aclc,
            },
            allowed_programs=allowed_programs,
            allowed_projects=allowed_projects,
            snapshot_builders_to_monitor=snapshot_builders_to_monitor,
            project_repo_snapshot_builders=['example-snapshot-project-repo'],
            android_host=android_host,
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

  def snapshot_build_step_data(api, builder='example-snapshot',
                               include_artifacts=True):
    output = build_pb2.Build.Output()
    output.properties['artifact_link'] = (
        f'gs://chromeos-image-archive/{builder}/R123-45678.0.0-123')
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
        step_name=f'Do update_android_config and create CL.Process builder {builder}.Find latest successful build for {builder}',
    )

  def existing_changes_step_data(api, action, host_url, repo_name,
                                 changes=None):
    return api.gerrit.set_query_changes_response(
        f"Do {action.__name__.strip('_')} and create CL.Create CL for {repo_name}.query for existing changes",
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
      existing_changes_step_data(
          api,
          action=_replicate_public_config,
          host_url="https://chromium-review.googlesource.com",
          repo_name="chromeos/project_public",
      ),
      existing_changes_step_data(
          api, action=_update_android_config,
          host_url="https://googleplex-android-review.googlesource.com",
          repo_name="device/google/desktop/example_program"),
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
      api.post_process(
          post_process.StepCommandContains,
          'Do update_android_config and create CL' \
              '.Process builder example-snapshot' \
              '.Process example_project from config.jsonproto' \
              '.Run generate-feature-xml from HAL for example_project',
          [
              'generate-feature-xml',
              '--from-hal-config',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'Do update_android_config and create CL' \
              '.Process builder example-snapshot' \
              '.copy feature from HAL XMLs for example_project',
          [
              '[CLEANUP]/googleplex-android_workspace/device/google/desktop/example/'
              'configs/features_from_hal/example_project',
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
          repo_name="chromeos/project_public",
      ),
      existing_changes_step_data(
          api, action=_update_android_config,
          host_url="https://googleplex-android-review.googlesource.com",
          repo_name="device/google/desktop/example_program", changes=[{
              '_number': 123,
              'project': 'example_repo',
          }]),
      api.post_process(
          post_process.StepTextContains,
          'Do update_android_config and create CL.Create CL for device/google/desktop/example_program.query for existing changes.query https://googleplex-android-review.googlesource.com',
          ['found 1 matching CL'],
      ),
      api.post_check(
          post_process.DoesNotRunRE,
          r'Do update_android_config and create CL.Create CL for .*.create gerrit change for .*\.git_cl upload'
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
      'update_android_config_project_repo',
      default_properties(
          snapshot_builders_to_monitor=['example-snapshot-project-repo']),
      config_repos_step_data(api),
      snapshot_build_step_data(api, 'example-snapshot-project-repo'),
      config_dlm_step_data(api),
      existing_changes_step_data(
          api, action=_update_android_config,
          host_url="https://googleplex-android-review.googlesource.com",
          repo_name="device/google/desktop/example_project"),
      api.post_process(
          post_process.StepCommandContains,
          'Do update_android_config and create CL.Process builder '
          'example-snapshot-project-repo.repo sync example_project',
          [
              'sync', '--current-branch', '--verbose', '--force-checkout',
              'device/google/desktop/example_project'
          ],
      ),
      api.post_process(post_process.DropExpectation),
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
          repo_name="chromeos/project_public",
      ),
      api.post_check(post_process.MustRunRE,
                     r'Do \w* and create CL.Create CL for .*.abandon CL 1'),
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
      'update_android_config_multiple_projects',
      default_properties(
          snapshot_builders_to_monitor=['example-snapshot', 'other-builder']),
      config_repos_step_data(api),
      snapshot_build_step_data(api, builder='example-snapshot'),
      snapshot_build_step_data(api, builder='other-builder'),
      config_dlm_step_data(api),
      existing_changes_step_data(
          api, action=_update_android_config,
          host_url="https://googleplex-android-review.googlesource.com",
          repo_name="device/google/desktop/example_program"),
      api.step_data(
          'Do update_android_config and create CL.Process builder example-snapshot.find jsonproto files',
          api.file.glob_paths([
              '[CLEANUP]/unzip_example-snapshot/example_program/chromeos-config-bsp-private-0.0.1/example_project/generated/config.jsonproto',
              '[CLEANUP]/unzip_example-snapshot/example_program/chromeos-config-bsp-private-0.0.1/another_project/generated/config.jsonproto',
          ])),
      api.post_process(
          post_process.MustRun,
          'Do update_android_config and create CL.Process builder example-snapshot.write combined HAL XML for example'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'update_android_config_one_builder_fails',
      default_properties(snapshot_builders_to_monitor=[
          'failing-builder', 'successful-builder'
      ]),
      config_repos_step_data(api),
      snapshot_build_step_data(api, builder='failing-builder'),
      snapshot_build_step_data(api, builder='successful-builder'),
      config_dlm_step_data(api),
      api.step_data(
          'Do update_android_config and create CL.Process builder failing-builder.unzip config_protos.zip',
          retcode=1),
      api.post_check(
          post_process.MustRun,
          'Do update_android_config and create CL.Process builder successful-builder.unzip config_protos.zip'
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'android-host',
      default_properties(android_host='android'),
      config_repos_step_data(api),
      snapshot_build_step_data(api),
      config_dlm_step_data(api),
      api.git.diff_check(True),
      existing_changes_step_data(
          api,
          action=_replicate_public_config,
          host_url="https://chromium-review.googlesource.com",
          repo_name="chromeos/project_public",
      ),
      existing_changes_step_data(
          api,
          action=_update_android_config,
          host_url="https://android-review.googlesource.com",
          repo_name="device/google/desktop/example_program",
      ),
      api.post_process(post_process.StepCommandContains,
                       'Do update_android_config and create CL.repo init', [
                           'init',
                           '--manifest-url',
                           'https://android.googlesource.com/platform/manifest',
                       ]),
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
          repo_name="chromeos/project_public",
      ),
      api.post_process(post_process.DoesNotRunRE, r'.*git_cl upload'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'update_component_ids',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      api.properties(android_target_to_cros_path={
          'project-trunk_staging-userdebug': 'src/project/program/project'
      }),
      existing_changes_step_data(
          api, action=_update_component_ids_from_android,
          host_url='https://chromium-review.googlesource.com',
          repo_name='chromeos/project/program/project'),
      api.git.diff_check(True),
      api.post_process(
          post_process.StepCommandContains,
          'Do update_component_ids_from_android and create CL.Process project-trunk_staging-userdebug.Download project-component_ids.star',
          [
              '--branch',
              'arsp-main',
              '--target',
              'project-trunk_staging-userdebug',
              '--results-json',
              '/path/to/tmp/json',
              '--verbose',
              '--filename',
              'project-component_ids.star',
          ],
      ),
      api.post_check(
          post_process.MustRun,
          'Do update_component_ids_from_android and create CL.Create CL for chromeos/project/program/project.git status',
      ),
      api.post_process(post_process.DropExpectation),
  )
