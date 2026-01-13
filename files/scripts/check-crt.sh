#!/bin/sh
if [ "$1" = "" ]
then
        echo "Uso $0 <cert file>"
        exit
fi

openssl x509 -in $1 -text -noout