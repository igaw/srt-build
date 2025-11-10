#!/bin/bash

COUNTER=1

for stressor in $(stress-ng --stressors); do

    id=$(printf "%04d%s" $COUNTER)
    filename=$id-stress-ng-$stressor.jinja2

    cp stress-ng.jinja2.template $filename

    sed -i "s/STRESSOR/$stressor/g" $filename

    let COUNTER++
done
