# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test responses for build API endpoints."""

import json
from typing import Any, Dict, Iterable, List, Optional, Union

from PB.chromiumos import common as common_pb2
from PB.chromiumos.signing import SigningStatus

from recipe_engine import recipe_test_api
from RECIPE_MODULES.chromeos.cros_build_api import api as cros_build_api

# Type hints to make type hints easier to understand.
_MethodName = str
_ServiceName = str
# _ResponseJson is a type alias for a dict representing a proto response method.
_ResponseJson = Dict[str, Any]


def jsonify(**kwargs) -> _ResponseJson:
  """Return the kwargs as a json string."""
  return json.dumps(kwargs, sort_keys=True)


class CrosBuildApiTestApi(recipe_test_api.RecipeTestApi):
  """Generate simple test data for all build API services.

  The data defined in this class is meant to serve as a simple default.
  Callers of cros_build_api may specify their own test data as they see
  fit.
  """
  INSTRUCTIONS = [
      'gs://chromeos-releases/beta-channel/grunt/14493.0.0/ChromeOS-recovery-R100-14493.0.0-grunt.instructions',
      'gs://chromeos-releases/beta-channel/grunt/14493.0.0/ChromeOS-base-R100-14493.0.0-grunt.instructions'
  ]

  def path(self, subpath: str) -> str:
    """Return the given subpath as a fully qualified path.

    Args:
      subpath: Relative path of interest.

    Returns:
      An absolute, qualified recipes path.
    """
    return str(self.m.path['start_dir'].join(subpath))

  def src_path(self, path: str) -> str:
    """Return the given path in the source tree checkout.

    Args:
      path (str): Relative path of interest.

    Returns:
      str: An absolute path to the source file.
    """
    return str(self.m.src_state.workspace_path.join(path))

  def result_path(self, relative_path: str) -> Dict[str, Union[str, int]]:
    """Construct a common_pb2.Path dict that mimics a ResultPath result.

    If you pass a common_pb2.ResultPath into a Build API request, then the BAPI
    field handler will extract any paths from the response object into that
    path. This method makes it easy for example response messages to mimic those
    responses.

    Args:
      relative_path: The filepath that would be extracted into the ResultPath.

    Returns:
      A dict representing a Path, like what the build API would return.
    """
    return {
        'path': str(self.m.path['cleanup'].join('my_tmp_dir', relative_path)),
        'location': 2,  # chromiumos.Path.Location.OUTSIDE
    }

  @property
  def android_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for AndroidService."""
    ret = {
        'GetLatestBuild':
            jsonify(android_version='7123456'),
        'MarkStable':
            jsonify(
                status='MARK_STABLE_STATUS_SUCCESS', android_atom={
                    'category': 'chromeos-base',
                    'package_name': 'android-vm-rvc',
                    'version': '7123456-r1',
                }),
        'WriteLKGB':
            jsonify(modified_files=[self.src_path('src/overlay/modified-file')]
                   ),
    }
    return ret

  @property
  def api_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate test responses for ApiService."""
    responses = {}
    responses['CompileProto'] = jsonify(
        modified_files=[
            {
                'path': self.src_path('chromite/api/gen/some_file_pb2.py')
            },
            {
                'path': self.src_path('chromite/api/gen_sdk/some_file_pb2.py')
            },
        ],
    )
    return responses

  @property
  def artifact_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for ArtifactsService."""
    _uploaded_path = lambda name: {'path': self.path(name), 'location': 2}

    ret = {
        'FetchMetadata':
            jsonify(filepaths=[{
                'path': {
                    'path': '[CACHE]/example.pb',
                    'location': 2
                }
            }]),
        'FetchPinnedGuestImageUris':
            jsonify(pinned_images=[{
                'filename': 'filename',
                'uri': 'https://example.com/filename'
            }]),
        'BuildSetup':
            jsonify(build_relevance='UNKNOWN'),
        'Get':
            jsonify(
                artifacts={
                    'legacy': {
                        'artifacts': [{
                            'artifact_type': 'EBUILD_LOGS',
                            'paths': [_uploaded_path('log.tar.gz')]
                        }]
                    },
                    'toolchain': {
                        'artifacts': [{
                            'artifact_type':
                                'UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE',
                            'paths': [_uploaded_path('afdo')]
                        }]
                    }
                }),
    }
    # Legacy, migrating to Get.
    bundle_response = jsonify(artifacts=[{
        'path': self.path('tmp/artifact.tar.gz')
    }])
    bundle_endpoints = [
        'BundleImageZip',
        'BundleTestUpdatePayloads',
        'BundleAutotestFiles',
        'BundleTastFiles',
        'BundlePinnedGuestImages',
        'BundleFirmware',
        'BundleEbuildLogs',
        'BundleChromeOSConfig',
        'BundleImageArchives',
        'BundleFpmcuUnittests',
        'BundleGceTarball',
        'BundleDebugSymbols',
    ]
    ret.update({endpoint: bundle_response for endpoint in bundle_endpoints})
    return ret

  @property
  def binhost_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for BinhostService."""
    responses = {}
    responses['PrepareBinhostUploads'] = jsonify(
        uploads_dir=self.path('uploads/dir'), upload_targets=[{
            'path': 'foo.tbz2'
        }])
    responses['PrepareDevInstallBinhostUploads'] = jsonify(upload_targets=[{
        'path': 'foo.tbz2'
    }])
    responses['PrepareChromeBinhostUploads'] = jsonify(upload_targets=[{
        'path': 'foo.tbz2'
    }])
    responses['SetBinhost'] = jsonify(output_file=self.path('BINHOST.conf'))
    responses['Get'] = jsonify(binhosts=[
        {
            'uri': 'gs://bucket1/some/path',
            'package_index': 'PackageIndex'
        },
        {
            'uri': 'gs://bucket2/diff/path',
            'package_index': 'PackageIndex'
        },
    ])
    responses['GetPrivatePrebuiltAclArgs'] = jsonify(args=[
        {
            'arg': 'arg1',
            'value': 'value1'
        },
        {
            'arg': 'arg2',
            'value': 'value2'
        },
    ])
    responses['RegenBuildCache'] = jsonify(modified_overlays=[{
        'path': self.src_path('src/overlay')
    }, {
        'path': self.src_path('src/partner-overlay')
    }])
    responses['GetBinhostConfPath'] = jsonify(
        conf_path=self.path('BINHOST.conf'))
    return responses

  @property
  def copybot_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for CopybotService."""
    responses = {}
    responses['RunCopybot'] = jsonify(
        failure_reason='FAILURE_UNKNOWN',
        merge_conflicts=[],
    )
    return responses

  @property
  def dependency_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for DependencyService."""
    responses = {}
    responses['GetBuildDependencyGraph'] = jsonify(
        dep_graph={
            'package_deps': [{
                'dependency_packages': [{
                    'category': 'chromeos-base',
                    'package_name': 'chrome-icu',
                    'version': '1-r52'
                }],
                'dependency_source_paths': [{
                    'path': 'some/source/dir',
                }],
            }],
        },
    )
    responses['GetToolchainPaths'] = jsonify(
        paths=[
            {
                'path': 'some/other/dir'
            },
        ],
    )
    responses['List'] = jsonify(
        package_deps=[
            {
                'category': 'chromeos-base',
                'package_name': 'chrome-icu',
                'version': '1-r52'
            },
            {
                'category': 'chromeos-base',
                'package_name': 'arc-setup',
                'version': '1-r123'
            },
        ],
    )
    return responses

  @property
  def dlc_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for DlcService."""
    responses = {}
    responses['GenerateDlcArtifactsList'] = jsonify(dlc_artifacts=[{
        'image_hash':
            '88d54cb6b5bba15a71ffda3ca75446eb453bf7fe393e3595d3bc52beb3b61711',
        'image_name':
            'dlc.img',
        'gs_uri_path':
            'gs://some/uri/prefix/for/dlc-1',
        'id':
            'dlc-1',
    }, {
        'image_hash':
            '99d54cb6b5bba15a71ffda3ca75446eb453bf7fe393e3595d3bc52beb3b61711',
        'image_name':
            'dlc.img',
        'gs_uri_path':
            'gs://some/uri/prefix/for/dlc-2',
        'id':
            'dlc-2',
    }])
    return responses

  @property
  def firmware_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for FirmwareService."""
    _uploaded_path = lambda name: {'path': self.path(name), 'location': 2}

    responses = {
        'BuildAllFirmware':
            jsonify(
                metrics={
                    'value': [
                        # Sample of typical ti50 size
                        {
                            'fw_section': [{
                                'region': 'total-image-size',
                                'used': 432012,
                                'track_on_gerrit': True,
                            },],
                            'platform_name': 'dauntless',
                            'target_name': 'ti50'
                        },
                        # Sample of typical EC size
                        {
                            'fw_section': [{
                                'region': 'RW_FLASH',
                                'used': 1234,
                                'total': 3456,
                                'track_on_gerrit': True,
                            },],
                            'platform_name': 'volteer',
                            'target_name': 'eldrid'
                        }
                    ]
                }),
        'TestAllFirmware':
            jsonify(
                # TODO(b/177907747): Provide sample data.
            ),
        'BundleFirmwareArtifacts':
            jsonify(
                artifacts={
                    'artifacts': [
                        {
                            'artifact_type': 'FIRMWARE_TARBALL',
                            'location': 'PLATFORM_EC',
                            'paths': [_uploaded_path('from_source.tar.bz2')]
                        },
                        {
                            'artifact_type': 'FIRMWARE_TARBALL_INFO',
                            'location': 'PLATFORM_EC',
                            'paths': [_uploaded_path('fw_metadata.json')],
                        },
                    ]
                },
            )
    }
    return responses

  @property
  def image_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for ImageService."""
    responses = {}
    responses['Create'] = jsonify(
        success=True,
        images=[
            {
                'path': self.path('cros/src/build/images/base.bin'),
                'type': 'IMAGE_TYPE_BASE'
            },
            {
                'path': self.path('cros/src/build/images/test.bin'),
                'type': 'IMAGE_TYPE_TEST'
            },
        ],
        failed_packages=[],
    )
    responses['CreateNetboot'] = '{}'

    responses['PushImage'] = jsonify(
        instructions=[{
            'instructions_file_path': file_name
        } for file_name in CrosBuildApiTestApi.INSTRUCTIONS],
    )
    responses['SignImage'] = jsonify(
        output_archive_dir='/path/to/signing/archive', signed_artifacts={
            'archive_artifacts': [{
                'build_target':
                    'kukui',
                'channel':
                    common_pb2.CHANNEL_CANARY,
                'input_archive_name':
                    'recovery_image.tar.xz',
                'keyset':
                    'devkeys',
                'status':
                    SigningStatus.STATUS_SUCCESS,
                'signed_artifacts': [{
                    'signed_artifact_name':
                        'chromeos_00000.0.0_kukui_recovery_canary-channel_devkeys'
                }]
            }]
        })

    responses['Test'] = jsonify(success=True)
    return responses

  @property
  def observability_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for ObservabilityService."""
    responses = {
        'GetImageSizeData':
            jsonify(image_data=[{
                'image_type':
                    'IMAGE_TYPE_BASE',
                'image_partition_data': [{
                    'partition_name': 'rootfs',
                    'packages': [
                        {
                            'identifier': {
                                'package_name': {
                                    'atom': 'cat/foo',
                                    'category': 'cat',
                                    'package_name': 'foo',
                                },
                                'package_version': {
                                    'major': 1,
                                    'revision': 1,
                                    'full_version': '1-r1',
                                }
                            },
                            'apparent_size': 1,
                            'disk_utilization_size': 4096,
                        },
                        {
                            'identifier': {
                                'package_name': {
                                    'atom': 'cat/bar',
                                    'category': 'cat',
                                    'package_name': 'bar',
                                },
                                'package_version': {
                                    'major': 1,
                                    'minor': 2,
                                    'patch': 3,
                                    'extended': 4,
                                    'revision': 5,
                                    'full_version': '1.2.3.4-r5',
                                }
                            },
                            'apparent_size': 1,
                            'disk_utilization_size': 4096,
                        },
                        {
                            'identifier': {
                                'package_name': {
                                    'atom': 'virtual/target',
                                    'category': 'virtual',
                                    'package_name': 'target',
                                },
                                'package_version': {
                                    'major': 0,
                                    'minor': 0,
                                    'patch': 1,
                                    'revision': 234,
                                    'full_version': '0.0.1-r234',
                                }
                            },
                            'apparent_size': 0,
                            'disk_utilization_size': 0,
                        },
                    ],
                    'partition_apparent_size': 2,
                    'partition_disk_utilization_size': 8192,
                }]
            }])
    }

    return responses

  @property
  def method_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for MethodService."""
    methods = []
    responses_by_service = self.responses_by_service(
        include_method_service=False)
    for service, responses_by_method in responses_by_service.items():
      for method in responses_by_method.keys():
        methods.append({'method': 'chromite.api.%s/%s' % (service, method)})
    methods.append({'method': 'chromite.api.MethodService/Get'})
    responses = {}
    responses['Get'] = jsonify(methods=methods,)
    return responses

  def uprev_methods_responses(self,
                              ebuilds) -> Dict[_MethodName, _ResponseJson]:
    """Returns response for uprev-related methods in PackageService.

    Args:
      ebuilds (list(str)): Modified ebuild file path, relative to the workspace directory.
    """
    modified_ebuilds = [{'path': self.src_path(e)} for e in ebuilds]
    responses = {}
    responses['Uprev'] = jsonify(version='1.2.3',
                                 modified_ebuilds=modified_ebuilds)
    responses['UprevVersionedPackage'] = jsonify(responses=[{
        'version': '1.2.3',
        'additional_commit_info': 'additional info to be rendered on uprev cl.',
        'modified_ebuilds': modified_ebuilds,
    }])
    responses['RevBumpChrome'] = jsonify(responses=[{
        'version': '1.2.3',
        'modified_ebuilds': modified_ebuilds
    }])
    return responses

  @property
  def package_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for PackageService."""
    responses = {}
    responses['BuildsChrome'] = jsonify(builds_chrome=True,)
    responses['GetAndroidMetadata'] = jsonify(
        android_package='android-vm-rvc',
        android_branch='git_rvc-arc',
        android_version='7123456',
    )
    responses['GetBuilderMetadata'] = jsonify(
        build_target_metadata=[{
            'android_container_branch': 'git_rvc-arc',
            'android_container_target': 'bertha',
            'android_container_version': '7978506',
            'arc_use_set': True,
            'build_target': 'eve',
            'ec_firmware_version': 'eve_v1.1.6659-ba2088ed3',
            'kernel_version': '5.4.163-r2827',
            'main_firmware_version': 'Google_Eve.9584.230.0',
        }], model_metadata=[{
            'ec_firmware_version': 'eve_v1.1.6659-ba2088ed3',
            'firmware_key_id': 'EVE',
            'main_readonly_firmware_version': 'Google_Eve.9584.107.0',
            'main_readwrite_firmware_version': 'Google_Eve.9584.230.0',
            'model_name': 'eve',
        }])
    responses['GetBestVisible'] = jsonify(package_info={
        'package_name': 'package',
        'category': 'category',
        'version': 'version'
    })
    responses['GetChromeVersion'] = jsonify(version='version',)
    responses['GetTargetVersions'] = jsonify(
        android_version='1',
        android_branch_version='git_rvc-arc',
        android_target_version='bertha',
        chrome_version='chrome_version',
        full_version='full_version',
        milestone_version='milestone_version',
        platform_version='platform_version',
    )
    responses['HasChromePrebuilt'] = jsonify(has_prebuilt=False)
    responses['HasPrebuilt'] = jsonify(has_prebuilt=False)
    responses['NeedsChromeSource'] = jsonify(
        needs_chrome_source=True,
        reasons=['LOCAL_UPREV', 'NO_PREBUILT'],
    )
    default_modified_ebuilds = [
        'src/overlay/foo.ebuild',
        'src/private-overlay/bar.ebuild',
    ]
    responses.update(self.uprev_methods_responses(default_modified_ebuilds))
    return responses

  @property
  def payload_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for PayloadService."""
    responses = {}
    remote_uri = ('gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
                  'chromeos_12345.0.0_zork_canary-channel_full_test.bin-abc')
    responses['GeneratePayload'] = jsonify(
        local_path='/tmp/aohiwdadoi/delta.bin', remote_uri=remote_uri)
    responses['GenerateUnsignedPayload'] = jsonify(unsigned_payloads=[{
        'version':
            1,
        'payload_file_path': {
            'path': '/tmp/aohiwdadoi/delta.bin',
            'location': 1,
        },
        'partition_names': ['foo-root', 'foo-kernel'],
        'tgt_partitions': [{
            'path': '/tmp/aohiwdadoi/tgt_root.bin',
            'location': 1,
        }, {
            'path': '/tmp/aohiwdadoi/tgt_kernel.bin',
            'location': 1,
        }]
    }])
    responses['FinalizePayload'] = jsonify(versioned_artifacts=[{
        'version': 1,
        'remote_uri': remote_uri,
        'file_path': {
            'path': '/tmp/aohiwdadoi/delta.bin.signed',
        }
    }])
    return responses

  @property
  def portage_explorer_service_responses(
      self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for PortageExplorerService."""
    responses = {}
    responses['RunSpiders'] = '{}'
    return responses

  @property
  def sdk_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for SdkService."""
    responses = {}
    responses['Clean'] = '{}'
    responses['Create'] = jsonify(version={'version': 123})
    responses['Delete'] = '{}'
    responses['Unmount'] = '{}'
    responses['Update'] = jsonify(version={'version': 123})
    responses['Uprev'] = jsonify(
        modified_files=[
            {
                'path':
                    self.src_path(
                        'src/third_party/chromiumos-overlay/chromeos/binhost/host/sdk_version.conf'
                    ),
                'location':
                    2,  # chromiumos.Path.Location.OUTSIDE
            },
            {
                'path':
                    self.src_path(
                        'src/overlays/overlay-amd64-host/prebuilt.conf'),
                'location':
                    2,  # chromiumos.Path.Location.OUTSIDE
            },
        ],
        version='2023.03.14.159265',
    )
    responses['BuildPrebuilts'] = jsonify(
        host_prebuilts_path={
            'path': self.path('chromiumos/out/var/lib/portage/pkgs'),
            'location': 2,  # chromiumos.Path.Location.OUTSIDE
        },
        target_prebuilts_path={
            'path': self.path('chromiumos/build/amd64-host/packages'),
            'location': 2,  # chromiumos.Path.Location.OUTSIDE
        },
    )
    responses['BuildSdkTarball'] = jsonify(
        sdk_tarball_path={
            'path': self.src_path('built-sdk.tar.xz'),
            'location': 2,  # chromiumos.Path.Location.OUTSIDE
        })
    responses['CreateManifestFromSdk'] = jsonify(
        manifest_path={
            'path': self.src_path('built-sdk.tar.xz.Manifest'),
            'location': 2,  # chromium.Path.Location.OUTSIDE
        })
    responses['CreateBinhostCLs'] = jsonify(cls=[
        'binhostcls:1',
        'binhostcls:8',
    ])
    responses['UploadPrebuiltPackages'] = '{}'
    responses['BuildSdkToolchain'] = jsonify(generated_files=[
        self.result_path('foo.tar.xz'),
        self.result_path('bar.tar.xz'),
    ])
    return responses

  @property
  def sdk_subtools_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for SdkSubtoolsService."""
    responses = {}
    responses['BuildSdkSubtools'] = jsonify(bundle_paths=[
        {
            'path':
                str(self.m.path['cache'].join(
                    'cros_chroot/out/sdk/tmp/cros-subtools/rustfmt')),
            'location':
                2,  # chromiumos.Path.Location.OUTSIDE
        },
        {
            'path':
                str(self.m.path['cache'].join(
                    'cros_chroot/out/sdk/tmp/cros-subtools/shellcheck')),
            'location':
                2,  # chromiumos.Path.Location.OUTSIDE
        },
    ])
    url = 'https://chrome-infra-packages.appspot.com/p/chromiumos/infra/tools/'
    responses['UploadSdkSubtools'] = jsonify(
        step_text='uploaded new instances for: rustfmt, shellcheck',
        summary_markdown=('uploaded new instances for: '
                          f'[rustfmt]({url}rustfmt/+/subtools_hash:5e5)'
                          f'[shellcheck]({url}shellcheck/+/subtools_hash:4f4)'),
    )
    return responses

  @property
  def sysroot_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for SysrootService."""
    responses = {}
    responses['Create'] = jsonify(
        sysroot={
            'path': self.path('/build/target'),
            'build_target': {
                'name': 'target'
            },
        },
    )
    responses['GenerateArchive'] = jsonify(
        sysroot_archive={
            'path': '/tmp/foo.zip',
            'location': 2,
        },
    )
    responses['InstallToolchain'] = jsonify(failed_package_data=[])
    responses['InstallPackages'] = jsonify(failed_package_data=[])
    return responses

  @property
  def test_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for TestService."""
    responses = {}
    responses['BazelTest'] = '{}'
    responses['BuildTargetUnitTest'] = jsonify(failed_package_data=[],)
    responses['BuildTestServiceContainers'] = jsonify(
        results=[{
            'success': {},
        }],
    )
    responses['ChromitePytest'] = '{}'
    responses['ChromiteUnitTest'] = '{}'
    responses['RulesCrosUnitTest'] = '{}'
    responses['DebugInfoTest'] = '{}'
    responses['VmTest'] = '{}'
    return responses

  @property
  def toolchain_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for ToolchainService."""
    responses = {}
    responses['PrepareForBuild'] = jsonify(build_relevance='UNKNOWN')
    responses['BundleArtifacts'] = jsonify(artifacts_info=[{
        'artifact_type': 'UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE',
        'artifacts': [{
            'path': 'my_output_artifact',
        },]
    }])
    responses['SetupToolchains'] = jsonify()
    return responses

  test_version = cros_build_api.Version(1, 1, 0)

  @property
  def version_service_responses(self) -> Dict[_MethodName, _ResponseJson]:
    """Generate responses for VersionService."""
    return {
        'Get':
            jsonify(
                version={
                    'major': self.test_version.major,
                    'minor': self.test_version.minor,
                    'bug': self.test_version.bug,
                })
    }

  def responses_by_service(
      self, include_method_service: bool = True
  ) -> Dict[_ServiceName, Dict[_MethodName, _ResponseJson]]:
    """Map service name to a dictionary of responses by method name.

    Args:
      include_method_service: used to include adding the endpoints of the
          MethodService to this map. This is a hack to allow
          `method_service_responses` to use this method to generate a full
          canned response without causing infinite recursion.

    Returns:
      A dict of {service_name: {endpoint_name: sample_response_json}}.
    """
    result = {
        'AndroidService': self.android_service_responses,
        'ApiService': self.api_service_responses,
        'ArtifactsService': self.artifact_service_responses,
        'BinhostService': self.binhost_service_responses,
        'CopybotService': self.copybot_service_responses,
        'DependencyService': self.dependency_service_responses,
        'DlcService': self.dlc_service_responses,
        'FirmwareService': self.firmware_service_responses,
        'ImageService': self.image_service_responses,
        'ObservabilityService': self.observability_service_responses,
        'PackageService': self.package_service_responses,
        'PayloadService': self.payload_service_responses,
        'PortageExplorerService': self.portage_explorer_service_responses,
        'SdkService': self.sdk_service_responses,
        'SdkSubtoolsService': self.sdk_subtools_service_responses,
        'SysrootService': self.sysroot_service_responses,
        'TestService': self.test_service_responses,
        'ToolchainService': self.toolchain_service_responses,
        'VersionService': self.version_service_responses,
    }
    if include_method_service:
      result['MethodService'] = self.method_service_responses
    return result

  def response_for_endpoint(
      self, endpoint: str,
      test_data: Optional[recipe_test_api.ModuleTestData] = None) -> str:
    """Return a fake response for the endpoint, if any.

    Args:
      endpoint: Fully qualified endpoint to get test response data for.
      test_data: The _test_data in the invoker RecipeApi object.

    Returns:
      JSON string containing fake response data for the endpoint.
    """
    service, method = endpoint.split('/')
    service = service.split('.')[-1]

    epilog = (
        'By convention, all build API calls must supply test data. '
        'You must either set test_output_data on your call to the build API '
        'or you must edit recipe_modules/cros_build_api/test_api.py to include '
        'test data for your endpoint.')
    responses_by_service = self.responses_by_service()
    if service not in responses_by_service:
      raise KeyError('No default test data for build API service '
                     '%s. %s' % (service, epilog))
    if method not in responses_by_service[service]:
      raise KeyError('No default test data for method '
                     '%s in service %s. %s' % (method, service, epilog))

    if service == 'PackageService':
      if test_data.enabled and 'set_upreved_ebuilds' in test_data:
        custom_responses = self.uprev_methods_responses(
            test_data.get('set_upreved_ebuilds'))
        if method in custom_responses:
          return custom_responses[method]

    return responses_by_service[service][method]

  @recipe_test_api.mod_test_data
  @staticmethod
  def set_upreved_ebuilds(ebuilds: List[str]) -> List[str]:
    """Set the return data from some uprev-related build API endpoints.

    Changes the modified ebuild files returned from these endpoints:
    - Uprev
    - UprevVersionedPackage
    - RevBumpChrome

    Args:
      ebuilds: Modified ebuild file paths, relative to the workspace directory.

    Returns:
      The same ebuilds that were passed in. But since this method is decorated
      with mod_test_data, you can pass this into api.test().
    """
    return ebuilds

  def set_api_return(self, parent_step_name: str, endpoint: str = '',
                     data: str = '', iteration: int = 1, retcode: int = 0,
                     step_name: str = '') -> recipe_test_api.TestData:
    """Set the return from a Build API call.

    Args:
      parent_step_name: Name of the parent step, such as 'prepare artifacts'.
      endpoint: Endpoint name, such as 'ImageService/Create'. Used to generate
        a step name.
      data: Build API response to return, as a JSON string.
      iteration: Which call this applies to for this step/endpoint.
      retcode: Return code for the Build API call.
      step_name: Name of the step given to the Build API call. If provided,
        overrides the automatically generated name using the endpoint name.

    Returns:
      Step_data for the test.
    """
    # Calls after the first one have the iteration number appended.
    step_name = step_name or 'call chromite.api.%s' % endpoint
    iteration = '' if iteration == 1 else ' (%d)' % iteration

    # If there is a parent step, append a dot (.) to signify the substep.
    # This allows us to have no dot if there is no parent step.
    parent_step_prefix = f'{parent_step_name}.' if parent_step_name else ''

    # Set the step data for the Build API call.
    substep = 'call build API script'
    ret = self.step_data(
        '%s%s%s.%s' % (parent_step_prefix, step_name, iteration, substep),
        self.m.file.read_raw(content=data), retcode=retcode)

    # Set the step data for reading the output if retcode in 0 or 2.
    if retcode in (0, 2):
      substep = 'read output file'
      ret += self.step_data(
          '%s%s%s.%s' % (parent_step_prefix, step_name, iteration, substep),
          self.m.file.read_raw(content=data))

    return ret

  @recipe_test_api.mod_test_data
  @staticmethod
  def call_version_service(value: bool) -> bool:
    """Whether to call VersionService/Get in testing.

    Args:
      value: if True, call VersionService/Get during testing.  If false, just
      use test_data or the default test answer, without calling the test method.

    Returns:
      The same value that was passed in. But since this method is decorated with
      mod_test_data, you can pass this into api.test().
    """
    return value

  @recipe_test_api.mod_test_data
  @staticmethod
  def remove_endpoints(value: Iterable[str]):
    """Remove the given endpoints from the API.

    Args:
      value: Endpoints to remove. For example: ['ArtifactsService/Get'].

    Returns:
      The same value that was passed in. But since this method is decorated with
      mod_test_data, you can pass this into api.test().
    """
    assert not isinstance(value, str), 'endpoint must not be type str'
    return set('chromite.api.{}'.format(x) for x in value)
