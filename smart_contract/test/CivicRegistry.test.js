const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("CivicRegistry", function () {
  let civicRegistry;
  let owner;
  let otherAccount;

  beforeEach(async function () {
    [owner, otherAccount] = await ethers.getSigners();
    const CivicRegistry = await ethers.getContractFactory("CivicRegistry");
    civicRegistry = await CivicRegistry.deploy();
  });

  describe("Deployment", function () {
    it("Should set the right owner", async function () {
      expect(await civicRegistry.owner()).to.equal(owner.address);
    });
  });

  describe("Issue Hashes", function () {
    it("Should store and retrieve issue hash", async function () {
      const issueId = 12345n;
      const dataHash = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef";
      
      await civicRegistry.connect(owner).storeIssueHash(issueId, dataHash);
      expect(await civicRegistry.getIssueHash(issueId)).to.equal(dataHash);
    });

    it("Should fail if storeIssueHash is called by non-owner", async function () {
      const issueId = 12345n;
      const dataHash = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef";

      await expect(
        civicRegistry.connect(otherAccount).storeIssueHash(issueId, dataHash)
      ).to.be.revertedWith("CivicRegistry: caller is not the owner");
    });
  });

  describe("Completion Hashes", function () {
    it("Should store and retrieve completion hash", async function () {
      const issueId = 12345n;
      const dataHash = "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890";
      
      await civicRegistry.connect(owner).storeCompletionHash(issueId, dataHash);
      expect(await civicRegistry.getCompletionHash(issueId)).to.equal(dataHash);
    });

    it("Should fail if storeCompletionHash is called by non-owner", async function () {
      const issueId = 12345n;
      const dataHash = "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890";

      await expect(
        civicRegistry.connect(otherAccount).storeCompletionHash(issueId, dataHash)
      ).to.be.revertedWith("CivicRegistry: caller is not the owner");
    });
  });

  describe("Personnel Hashes", function () {
    it("Should store and retrieve personnel hash", async function () {
      const userId = 99999n;
      const dataHash = "0x7777777777777777777777777777777777777777777777777777777777777777";
      
      await civicRegistry.connect(owner).storePersonnelHash(userId, dataHash);
      expect(await civicRegistry.getPersonnelHash(userId)).to.equal(dataHash);
    });

    it("Should fail if storePersonnelHash is called by non-owner", async function () {
      const userId = 99999n;
      const dataHash = "0x7777777777777777777777777777777777777777777777777777777777777777";

      await expect(
        civicRegistry.connect(otherAccount).storePersonnelHash(userId, dataHash)
      ).to.be.revertedWith("CivicRegistry: caller is not the owner");
    });
  });
});
