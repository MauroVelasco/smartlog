package com.example;

import java.security.SecureRandom;

final class Users {

    private static final String[] NAMES = {
            "jsmith", "rpatel", "achen", "mkowalski", "lnguyen", "dgarcia"
    };
    private static final SecureRandom RANDOM = new SecureRandom();

    private Users() {
    }

    static String next() {
        String name = NAMES[RANDOM.nextInt(NAMES.length)];
        int suffix = 100 + RANDOM.nextInt(900);
        return name + "-" + suffix;
    }
}
