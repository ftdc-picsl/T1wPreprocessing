#!/bin/bash

# Get git information and build docker image

if [[ $# -gt 0 ]] ; then
    echo "usage: $0 [-h]"
    echo "Builds a docker image from tagged source, and embeds git info. Run from source directory."
    echo
    echo "For a tagged commit vX.Y.Z, the docker image will be tagged as X.Y.Z."
    echo
    exit 1
fi

# Get git information
status=$( git status -s )

# status should be empty if the repository is clean
if [[ ! -z "$status" ]] ; then
    echo "Repository is not clean - see git status"
    exit 1
fi

gitRemote=$( git remote get-url origin )

# Get the git hash or tag
hash=$( git rev-parse HEAD )

# See if there's a tag
gitTag=$( git describe --tags --abbrev=0 --exact-match $hash 2>/dev/null || echo "" )

if [[ -z "$gitTag" ]]; then
    echo "No tag found for commit $hash"
    exit 1
fi

dockerTag=${gitTag:1}

if [[ ! "$dockerTag" == "v{$gitTag}" ]]; then
    echo "Tag $dockerTag does not match git tag $gitTag"
    exit 1
fi

# Put this in docker labels
dockerCommit=$gitTag

# Build the docker image
docker build -t "ftdc-t1w-preproc:$dockerTag" . --build-arg GIT_REMOTE="$gitRemote" --build-arg GIT_COMMIT="$gitTag"

if [[ $? -ne 0 ]] ; then
    echo "Docker build failed - see output above"
    exit 1
else
    echo
    echo "Build successful: ftdc-t1w-preproc:$dockerTag"
    echo
fi