# Build environment corrections (2026-11-04)

Native build images install Git because tagged application sources may use CMake
FetchContent. Product source and build recipes are unchanged.

Rocky targets name the major series (9 or 10); point releases retain that series.
Other numeric series, including Ubuntu 24.04, remain exact. Debian sid is checked
against the official image's apt deb822 `Suites: sid` line because os-release may
identify the next stable codename. Distribution and architecture checks remain.
The assignment-based bootstrap and its acceptance/rejection tests were retired with the old `core-ci-*.yml` workflows; current workers validate source declarations through `coreci.common` and the retained CTest suite.

The hook container uses a disposable anonymous disk-backed /work volume instead
of a 4 GiB RAM filesystem. The image creates /work with mode 1777 so UID1000 can
write it. Docker --rm removes the volume. Source, definition, assignment and
prerequisite mounts remain read-only; capability and resource limits stay intact.
The independent validator retains its small tmpfs and offline network policy.
This corrects observed OpenWrt SDK ENOSPC without exposing host inputs for writes.

Production delta: native.py 0, native_container.py +3, explicitly owner-approved.
No application tag or non-CI application file changes.

The hook process does not reap orphaned SDK helpers itself. Docker --init supplies
the runtime's init process while retaining the256-process limit. A numeric Docker
UID alone also has no passwd entry in several base images; create the build
account when UID1000 is absent, retaining existing accounts. This lets unchanged
SNode.C initialization and tests resolve their user and primary group.
The combined isolated fixture validates UID/GID, writable /work, read-only root,
and400process trees with zero remaining zombies. This is not full-chain acceptance.
Follow-up production delta: native.py +2; total worker change +5. Owner authorized
necessary additional lines in advance, with accounting after successful acceptance.

CPack collection explicitly sets CPACK_OUTPUT_FILE_PREFIX as well as -B; a source
configuration may otherwise override -B and produce valid packages outside the
collector directory. The real DEB/RPM fixture now includes such an override.
Install file in Debian build images for CPack's dependency inspection.

Foreign-architecture compilation made steady progress but exceeded50minutes.
Keep every source test enabled: allow5hours for the source hook,5h20 for its
container,1hour for image preparation/CPack and6hours for the GitHub job. These
are failure deadlines, not dispatch/readiness policy. Native resource limits stay.
Current cumulative Python delta versus9102417: native.py+3, native_container.py+4,
total+7; reusable build workflow line count unchanged. Further necessary growth
was explicitly authorized by the owner, to be reported after successful acceptance.
