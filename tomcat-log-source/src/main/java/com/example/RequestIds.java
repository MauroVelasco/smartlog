package com.example;

import java.security.SecureRandom;

final class RequestIds {

    private static final char[] HEX = "0123456789abcdef".toCharArray();
    private static final SecureRandom RANDOM = new SecureRandom();

    private RequestIds() {
    }

    static String next() {
        char[] suffix = new char[6];
        for (int i = 0; i < suffix.length; i++) {
            suffix[i] = HEX[RANDOM.nextInt(HEX.length)];
        }
        return "req-" + new String(suffix);
    }
}
