// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {PaymentChannel} from "../src/PaymentChannel.sol";
import {MockIdentityRegistry} from "../src/MockIdentityRegistry.sol";
import {MockReputationRegistry} from "../src/MockReputationRegistry.sol";

/// @notice Deploy all contracts for local testing (Anvil)
contract DeployAllScript is Script {
    function run() external {
        vm.startBroadcast();

        PaymentChannel pc = new PaymentChannel();
        console.log("PaymentChannel deployed at:", address(pc));

        MockIdentityRegistry identity = new MockIdentityRegistry();
        console.log("MockIdentityRegistry deployed at:", address(identity));

        MockReputationRegistry reputation = new MockReputationRegistry();
        console.log("MockReputationRegistry deployed at:", address(reputation));

        vm.stopBroadcast();
    }
}
