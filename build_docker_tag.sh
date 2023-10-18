#!/bin/bash

# Get git information and build docker image

if [[ $# -gt 0 ]] ; then
    echo "usage: $0 <tag> [-h]"
    echo "Builds a docker image with the given tag, and embeds git info. Run from source directory."
    echo
    echo "The tag should be numeric, matching the commit tag in git, eg '0.1.0' for tag 'v0.1.0'"
    echo
    exit 1
fi

dockerTag=$1

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

if [[ ! "$dockerTag" == "v{$gitTag}" ]]; then
    echo "Tag $dockerTag does not match git tag $gitTag"
    exit 1
fi

# Put this in docker labels
dockerCommit=$gitTag

# Build the docker image
docker build -t "cookpa/ftdc-t1w-preproc:$dockerTag" . --build-arg GIT_REMOTE="$gitRemote" --build-arg GIT_COMMIT="$gitTag"