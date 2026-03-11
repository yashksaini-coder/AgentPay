// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {PaymentChannel} from "../src/PaymentChannel.sol";

contract DeployScript is Script {
    function run() external {
        vm.startBroadcast();
        PaymentChannel pc = new PaymentChannel();
        console.log("PaymentChannel deployed at:", address(pc));
        vm.stopBroadcast();
    }
}
